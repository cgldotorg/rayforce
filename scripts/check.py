#!/usr/bin/env python3
"""Build once, then run every selected Rayforce case in an isolated process.

Requires Python 3, CTest and a POSIX host. The ordinary Make targets remain
available on other platforms. Run reports live under build/check/.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import functools
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def capacity() -> tuple[int, int]:
    """Respect inherited CPU affinity and leave RAM for the desktop."""
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1
    available = 8 * 1024**3
    if Path('/proc/meminfo').exists():
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                available = int(line.split()[1]) * 1024
    return cpus, available


@contextlib.contextmanager
def lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


@functools.cache
def network_test(name: str) -> bool:
    # Some tests also assert that a fixed port is *closed*. Keep these in
    # the same group as server-spawning tests. The file lock spans CTest runs.
    name = name.removeprefix('equiv/')
    if name.startswith('rfl/'):
        source = (ROOT / 'test' / (name + '.rfl')).read_text()
        return any(token in source for token in ('.ipc.', 'pkill', ':listen', '-p ', '--port'))
    # The C IPC harness binds port 0. Only these C tests use fixed ports;
    # serializing whole C groups also serializes unrelated timer/PTY waits.
    return name in {'runtime/syscov_hopen_with_credentials',
                    'repl/run/piped/listen_ok', 'repl/run/piped/with_poll_listen',
                    'repl/pty/listen_ok'}


def terminate_group(process: subprocess.Popen) -> None:
    # The test may have spawned servers. Reap only this worker's process
    # group, including on timeout or interruption; never broad pkill here.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    # Wait for the whole group, not just its leader. CTest workers need
    # time to clean up the separate process groups of their test servers.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def worker(args) -> int:
    work_root = Path(args.work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    name = args.case
    guard = lock(Path(args.lock_dir) / 'network.lock') if network_test(name) else contextlib.nullcontext()
    # Short absolute scratch paths also fit legacy fixture buffers. Put
    # scratch on the home filesystem, rather than the often-full /tmp tmpfs.
    scratch_root = Path.home() / '.cache/rft'
    scratch_root.mkdir(parents=True, exist_ok=True)
    with guard, tempfile.TemporaryDirectory(prefix='case-', dir=work_root) as tmp, \
            tempfile.TemporaryDirectory(prefix='', dir=scratch_root) as scratch:
        cwd = Path(tmp)
        for entry in ('test', 'src', 'include', 'fuzz'):
            (cwd / entry).symlink_to(ROOT / entry, target_is_directory=True)
        (cwd / 'Makefile').symlink_to(ROOT / 'Makefile')
        (cwd / 'build').mkdir()
        for fixture in ('libhostfn.so', 'libhostfn_mark.so'):
            if (ROOT / 'build' / fixture).exists():
                (cwd / 'build' / fixture).symlink_to(ROOT / 'build' / fixture)
        (cwd / 'rayforce').symlink_to(Path(args.server))
        env = os.environ.copy()
        env['RAYFORCE_CORES'] = str(args.cores)
        env['RAY_TEST_TMPDIR'] = scratch
        env.pop('RFL_ROOT', None)
        env.pop('RFL_UPDATE', None)
        process = subprocess.Popen([args.binary, '--exact', name], cwd=cwd, env=env,
                                   start_new_session=True)
        def interrupted(signum, _frame):
            raise SystemExit(128 + signum)
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        try:
            return process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            print(f'TIMEOUT after {args.timeout}s: {name}', flush=True)
            return 124
        finally:
            terminate_group(process)


def cmake_quote(value: str) -> str:
    # Bracket arguments preserve spaces, semicolons and backslashes.
    equals = '='
    while ']' + equals + ']' in value:
        equals += '='
    return '[' + equals + '[' + value + ']' + equals + ']'


def discover(binary: Path, filters: list[str]) -> list[str]:
    cmd = [str(binary), '--list']
    env = os.environ.copy()
    env.pop('RFL_ROOT', None)
    env.pop('RFL_UPDATE', None)
    result = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True, check=True)
    names = result.stdout.splitlines()
    # large/ remains opt-in, including when combined with other filters.
    if any(f.startswith('large/') for f in filters):
        result = subprocess.run(cmd + ['-f', 'large/'], cwd=ROOT, env=env,
                                text=True, capture_output=True, check=True)
        names += result.stdout.splitlines()
    if not names or len(set(names)) != len(names):
        raise ValueError('test inventory is empty or contains duplicate names')
    if filters:
        names = [name for name in names if any(f in name for f in filters)]
    if not names:
        raise ValueError('filters selected zero tests')
    return sorted(names)


def configure(run_dir: Path, names: list[str], args, timings: dict) -> None:
    # Expensive cases first to avoid a serial tail; short cases fill gaps.
    # Start the serial network chain immediately while CPU-heavy work fills
    # the other slots, instead of leaving socket/timer tests as a long tail.
    names = sorted(names, key=lambda n: (not network_test(n), -timings.get(n, 0), n))
    lines = ['# Generated by scripts/check.py; do not edit.']
    for name in names:
        command = [sys.executable, str(Path(__file__).resolve()), '--worker',
                   '--case', name, '--binary', str(ROOT / 'rayforce.test.fast'),
                   '--server', str(ROOT / 'rayforce.fast'), '--work-root', str(run_dir / 'work'),
                   '--lock-dir', str(args.lock_dir), '--cores', str(args.cores),
                   '--timeout', str(args.timeout)]
        qname = cmake_quote(name)
        lines.append('add_test(' + qname + ' ' + ' '.join(map(cmake_quote, command)) + ')')
        props = ['SKIP_RETURN_CODE', '77', 'TIMEOUT', str(args.timeout + 15)]
        if network_test(name):
            props += ['RESOURCE_LOCK', 'rayforce_network']
        lines.append('set_tests_properties(' + qname + ' PROPERTIES ' + ' '.join(props) + ')')
    (run_dir / 'CTestTestfile.cmake').write_text('\n'.join(lines) + '\n')
    (run_dir / 'inventory.json').write_text(json.dumps(names, indent=2) + '\n')


def summarize(run_dir: Path, expected: list[str], elapsed: float, build_seconds: float,
              args, timing_file: Path, cpu_seconds: float) -> bool:
    report = run_dir / 'junit.xml'
    if not report.exists():
        raise ValueError('CTest did not produce a result report')
    cases = list(ET.parse(report).getroot().iter('testcase'))
    actual = [c.attrib['name'] for c in cases]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError('CTest result inventory differs from selected tests')
    failed = [c.attrib['name'] for c in cases if c.find('failure') is not None or c.find('error') is not None]
    skipped = [c.attrib['name'] for c in cases if c.find('skipped') is not None]
    timings = json.loads(timing_file.read_text()) if timing_file.exists() else {}
    timings.update({c.attrib['name']: float(c.attrib.get('time', 0)) for c in cases})
    timing_file.write_text(json.dumps(timings, sort_keys=True, indent=2) + '\n')
    result = {'selected': len(expected), 'passed': len(cases) - len(failed) - len(skipped),
              'failed': failed, 'skipped': skipped, 'test_seconds': round(elapsed, 3),
              'build_seconds': round(build_seconds, 3), 'jobs': args.jobs,
              'test_cpu_seconds': round(cpu_seconds, 3),
              'average_busy_cores': round(cpu_seconds / max(elapsed, 0.001), 2),
              'runtime_workers': args.cores, 'build_jobs': args.build_jobs,
              'build_config': (ROOT / 'build/.fast-config').read_text(),
              'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
    (run_dir / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f"\n{result['passed']} passed, {len(skipped)} skipped, {len(failed)} failed; "
          f"{elapsed:.2f}s testing + {build_seconds:.2f}s build.\nResults: {run_dir}", flush=True)
    return not failed


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be positive')
    return number


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-j', '--jobs', type=positive, help='concurrent test processes (auto by CPU/RAM)')
    parser.add_argument('--build-jobs', type=positive)
    parser.add_argument('--cores', type=int, default=2, help='runtime worker threads per test; default 2')
    parser.add_argument('-f', '--filter', action='append', default=[], help='name substring; repeated filters are a union')
    parser.add_argument('--optimization', choices=('0', '1', '2'), default='1')
    parser.add_argument('--build-target', choices=('test-fast-build', 'release', 'debug', 'hardened', 'lib'),
                        default='test-fast-build', help='other targets require --build-only')
    parser.add_argument('--march', default=os.environ.get('RAY_MARCH', 'native'))
    parser.add_argument('--timeout', type=positive, default=600, help='per-case seconds')
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--build-only', action='store_true')
    parser.add_argument('--configure-only', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--case', help=argparse.SUPPRESS)
    parser.add_argument('--binary', help=argparse.SUPPRESS)
    parser.add_argument('--server', help=argparse.SUPPRESS)
    parser.add_argument('--work-root', help=argparse.SUPPRESS)
    parser.add_argument('--lock-dir', type=Path, default=Path.home() / '.cache/rayforce-check-locks', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.cores < 0:
        parser.error('--cores must be nonnegative')
    if args.worker:
        return worker(args)
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    if args.build_target != 'test-fast-build' and not args.build_only:
        parser.error('--build-target requires --build-only; check always uses matched sanitizer binaries')
    if os.environ.get('RFL_UPDATE') not in (None, '', '0'):
        parser.error('RFL_UPDATE is unsupported in parallel checks; use the serial harness to update goldens')
    if not args.build_only and not shutil.which('ctest'):
        parser.error('ctest is required (install CMake)')
    cpus, available = capacity()
    usable_gib = max(1, available // 1024**3 - 8)
    # Two SMT threads per physical core on the target Threadripper. Most
    # small cases keep their pool idle; 32 processes beat 16 in measurement.
    # Larger explicit runtime pools reduce the default process count.
    args.jobs = args.jobs or max(1, min(cpus // max(2, args.cores), usable_gib, 32))
    args.build_jobs = args.build_jobs or max(1, min(max(1, cpus // 2), usable_gib))
    # Coordinate cooperating runs across worktrees. Each run uses the full
    # chosen budget; this avoids several independent 64-way build/test floods.
    print('Waiting for Rayforce check reservation...', flush=True)
    with lock(args.lock_dir / 'check.lock'):
        print(f'CPU threads: {cpus}; available RAM: {available / 1024**3:.1f} GiB; '
              f'build jobs: {args.build_jobs}; test processes: {args.jobs}; '
              f'runtime workers/process: {args.cores}', flush=True)
        run_dir = ROOT / 'build/check' / (time.strftime('%Y%m%dT%H%M%S') + f'-{os.getpid()}')
        run_dir.mkdir(parents=True)
        build_seconds = 0.0
        if not args.no_build:
            env = os.environ.copy()
            env.pop('MAKEFLAGS', None)
            env.pop('MFLAGS', None)
            env['CCACHE_BASEDIR'] = str(ROOT)
            env['CCACHE_DIR'] = str(Path.home() / '.cache/rayforce-ccache')
            env.setdefault('CCACHE_MAXSIZE', '10G')
            compiler = os.environ.get('CC', 'clang')
            if shutil.which('ccache') and 'ccache' not in compiler:
                compiler = 'ccache ' + compiler
            command = ['make', f'-j{args.build_jobs}', args.build_target, f'CC={compiler}',
                       f'CHECK_OPT=-O{args.optimization}', f'RAY_MARCH={args.march}']
            if shutil.which('ld.lld') and 'clang' in compiler:
                command += ['LOCAL_LINK_FLAGS=-fuse-ld=lld']
            start = time.monotonic()
            with (run_dir / 'build.log').open('w') as output:
                process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=output,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    status = process.wait()
                except BaseException:
                    terminate_group(process)
                    raise
            build_seconds = time.monotonic() - start
            print(f'Build: {build_seconds:.2f}s; log: {run_dir / "build.log"}', flush=True)
            if status:
                print((run_dir / 'build.log').read_text()[-6000:])
                return status
        if args.build_only:
            return 0
        names = discover(ROOT / 'rayforce.test.fast', args.filter)
        timing_file = ROOT / 'build/check/timings.json'
        timings = json.loads(timing_file.read_text()) if timing_file.exists() else {}
        configure(run_dir, names, args, timings)
        print(f'Selected {len(names)} unique tests (including equivalence cases).', flush=True)
        if args.configure_only:
            print(run_dir)
            return 0
        command = ['ctest', '--test-dir', str(run_dir), '-j', str(args.jobs),
                   '--output-on-failure', '--no-tests=error', '--output-junit', str(run_dir / 'junit.xml')]
        start = time.monotonic()
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_before = usage.ru_utime + usage.ru_stime
        # Keep the complete log, while printing progress at most every 10s.
        with (run_dir / 'ctest.log').open('w') as output:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, start_new_session=True)
            last = start
            try:
                for line in process.stdout:
                    output.write(line)
                    if time.monotonic() - last > 10:
                        output.flush()
                        print(line.rstrip(), flush=True)
                        last = time.monotonic()
                status = process.wait()
            except BaseException:
                terminate_group(process)
                raise
        elapsed = time.monotonic() - start
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        good = summarize(run_dir, names, elapsed, build_seconds, args, timing_file,
                         usage.ru_utime + usage.ru_stime - cpu_before)
        if status or not good:
            print((run_dir / 'ctest.log').read_text()[-5000:])
            return status or 1
        return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f'check: {error}', file=sys.stderr)
        sys.exit(2)
