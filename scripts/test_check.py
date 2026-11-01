#!/usr/bin/env python3
"""Process-level regression checks for check.py's isolation and cleanup."""
import os
import importlib.util
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

RUNNER = Path(__file__).with_name('check.py')
SPEC = importlib.util.spec_from_file_location('rayforce_check', RUNNER)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
FAKE = '''#!/usr/bin/env python3
import os, pathlib, subprocess, sys, time
case = sys.argv[2]
if case == "skip": sys.exit(77)
if case == "fail": sys.exit(1)
if case == "timeout":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    pathlib.Path(os.environ["CHILD_PID_FILE"]).write_text(str(child.pid))
    time.sleep(60)
p = pathlib.Path("same-relative-fixture")
p.write_text(str(os.getpid()))
time.sleep(0.2)
assert p.read_text() == str(os.getpid())
assert pathlib.Path(os.environ["RAY_TEST_TMPDIR"]).is_dir()
assert not os.environ["RAY_TEST_TMPDIR"].startswith("/tmp/")
assert pathlib.Path("rayforce").exists()
assert pathlib.Path("src/table/table.c").exists()
'''


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rayforce-runner-selftest-')
        self.root = Path(self.temp.name)
        self.fake = self.root / 'fake-test'
        self.fake.write_text(FAKE)
        self.fake.chmod(0o755)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, case, timeout=5):
        return [sys.executable, str(RUNNER), '--worker', '--case', case,
                '--binary', str(self.fake), '--server', str(self.fake),
                '--work-root', str(self.root / 'work'), '--lock-dir', str(self.root / 'locks'),
                '--cores', '2', '--timeout', str(timeout)]

    def test_parallel_workers_have_separate_relative_files(self):
        processes = [subprocess.Popen(self.command('normal')) for _ in range(8)]
        self.assertEqual([p.wait(timeout=10) for p in processes], [0] * 8)
        self.assertEqual(list((self.root / 'work').iterdir()), [])

    def test_failure_and_skip_exit_codes_survive(self):
        for case, expected in [('fail', 1), ('skip', 77)]:
            with self.subTest(case=case):
                self.assertEqual(subprocess.run(self.command(case), timeout=10).returncode, expected)

    def assert_dead(self, pid):
        for _ in range(100):
            status = Path(f'/proc/{pid}/status')
            if not status.exists() or '\nState:\tZ' in status.read_text():
                return
            time.sleep(0.02)
        self.fail(f'child {pid} survived worker cleanup')

    def test_timeout_reaps_server_and_removes_scratch(self):
        pid_file = self.root / 'child.pid'
        env = dict(os.environ, CHILD_PID_FILE=str(pid_file))
        status = subprocess.run(self.command('timeout', 1), env=env, timeout=10).returncode
        self.assertEqual(status, 124)
        self.assert_dead(int(pid_file.read_text()))
        self.assertEqual(list((self.root / 'work').iterdir()), [])

    def test_interrupt_reaps_server(self):
        pid_file = self.root / 'child.pid'
        env = dict(os.environ, CHILD_PID_FILE=str(pid_file))
        process = subprocess.Popen(self.command('timeout'), env=env)
        try:
            for _ in range(100):
                if pid_file.exists():
                    break
                time.sleep(0.02)
            self.assertTrue(pid_file.exists())
            process.send_signal(signal.SIGTERM)
            self.assertEqual(process.wait(timeout=10), 143)
            self.assert_dead(int(pid_file.read_text()))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_dispatcher_interrupt_reaches_separate_test_process_group(self):
        pid_file = self.root / 'child.pid'
        env = dict(os.environ, CHILD_PID_FILE=str(pid_file))
        dispatcher = [sys.executable, '-c',
                      'import subprocess,sys; subprocess.Popen(sys.argv[1:]).wait()']
        process = subprocess.Popen(dispatcher + self.command('timeout', 30),
                                   env=env, start_new_session=True)
        try:
            for _ in range(200):
                if pid_file.exists():
                    break
                time.sleep(0.02)
            self.assertTrue(pid_file.exists())
            CHECK.terminate_group(process)
            self.assertIsNotNone(process.poll())
            self.assert_dead(int(pid_file.read_text()))
            self.assertEqual(list((self.root / 'work').iterdir()), [])
        finally:
            CHECK.terminate_group(process)


if __name__ == '__main__':
    unittest.main()
