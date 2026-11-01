#!/usr/bin/env python3
"""Independent persisted-value, width and crash checks for S0 SYM append.

Run with RELEASE OUTDIR [OPTIMIZED_DEBUG].  The optional third argument is
the optimized `rayforce.fast` binary, needed for DEBUG-only fault hooks.
"""
import csv
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

release = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
fault_binary = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else None
out.mkdir(parents=True, exist_ok=False)
records = []
serial = 0


def run(text, binary=release, extra=None, asynchronous=False):
    global serial
    serial += 1
    source = out / f'case-{serial}.rfl'
    source.write_text(text + '\n')
    args = [str(binary), '-c', '2', '-f', str(source)]
    env = os.environ.copy()
    if extra: env.update(extra)
    if asynchronous:
        return subprocess.Popen(args, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
    p = subprocess.run(args, env=env, capture_output=True, text=True, timeout=120)
    (out / f'case-{serial}.log').write_text(p.stdout + p.stderr)
    return p


def ok(text, binary=release):
    p = run(text, binary)
    if p.returncode or 'error:' in p.stdout + p.stderr:
        raise AssertionError((text, p.returncode, p.stdout, p.stderr))
    return p.stdout


def record(name, **details):
    records.append({'test': name, 'status': 'pass', **details})
    metadata = {'release': str(release), 'release_sha256': hashlib.file_digest(
        release.open('rb'), 'sha256').hexdigest(), 'tests': records}
    if fault_binary:
        metadata['optimized_debug'] = str(fault_binary)
        metadata['optimized_debug_sha256'] = hashlib.file_digest(
            fault_binary.open('rb'), 'sha256').hexdigest()
    (out / 'results.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print('PASS', name, flush=True)


def current(table):
    return table / (table / '.current').read_text().strip()


def dump(table, sym, label):
    path = out / f'{label}.csv'
    ok(f'(.csv.write (.db.splayed.get "{table}" "{sym}") "{path}")')
    with path.open(newline='') as f:
        rows = list(csv.reader(f))
    # A one-column SYM null is emitted as an empty physical line; Python's
    # CSV reader returns [] for it, while it represents one empty field.
    return [([''] if len(rows[0]) == 1 and not row else row) for row in rows]


def seed_single(label, count, copies=1, index=False):
    root = out / label
    root.mkdir()
    path = root / 'seed.csv'
    with path.open('w', newline='') as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerow(['s'])
        for _ in range(copies):
            writer.writerows((f's{i}',) for i in range(count))
    table, sym = root / 'table', root / '.sym'
    load = f'(.csv.read [SYMBOL] "{path}")'
    if index:
        load = f'(table [s] (list (.idx.hash (at {load} \'s))))'
    ok(f'(.db.splayed.set "{table}" {load} "{sym}" {{compress: false}})\n'
       f'(.db.splayed.set "{table}" {load} "{sym}" {{compress: false}})')
    return root, table, sym, current(table)


def width(path):
    with path.open('rb') as f:
        head = f.read(32)
    assert len(head) == 32
    return head[19] & 3


def append_expr(table, sym, values):
    atoms = ' '.join(json.dumps(x) for x in values)
    return f'(.db.splayed.append "{table}" (table [s] (list (as \'SYMBOL [{atoms}]))) "{sym}")'


def exact_case(label, count, values, expected_old_width, expected_new_width):
    root, table, sym, prior = seed_single(label, count)
    assert width(prior / 's') == expected_old_width, (label, width(prior / 's'))
    before = dump(table, sym, label + '-before')
    assert len(before) == count + 1
    ok(append_expr(table, sym, values))
    now = current(table)
    assert width(now / 's') == expected_new_width, (label, width(now / 's'))
    assert dump(table, sym, label + '-after') == before + [[v] for v in values]
    assert dump(prior, sym, label + '-prior') == before
    record(label, rows_before=count, old_width=expected_old_width,
           new_width=expected_new_width, all_values_and_old_generation=True)
    return root, table, sym, prior


# The first two cases retain narrow widths and add a previously unknown
# symbol while staying within the same width. The next two cross each limit.
exact_case('w8-stable-new-and-null', 3, ['s2', 'fresh', '', 's0'], 0, 0)
exact_case('w16-stable-new-and-null', 256, ['s255', 'fresh', '', 's0'], 1, 1)
exact_case('w8-to-w16', 254, ['fresh-a', 'fresh-b'], 0, 2)
exact_case('w16-to-w32', 65534, ['fresh-a', 'fresh-b'], 1, 2)

# Grow the shared domain through another table before this table's append.
# The old column no longer fits the newer domain width even though this
# append itself does not cross a boundary.
root, table, sym, prior = seed_single('external-domain-growth', 3)
othercsv = root / 'external.csv'
with othercsv.open('w', newline='') as f:
    writer = csv.writer(f, lineterminator='\n')
    writer.writerow(['u'])
    writer.writerows((f'outside-{i}',) for i in range(260))
ok(f'(.db.splayed.set "{root}/other" (.csv.read [SYMBOL] "{othercsv}") "{sym}" {{compress: false}})')
before = dump(table, sym, 'external-before')
ok(append_expr(table, sym, ['outside-259', 's2']))
assert width(current(table) / 's') == 2
assert dump(table, sym, 'external-after') == before + [['outside-259'], ['s2']]
assert dump(prior, sym, 'external-prior') == before
record('saved width insufficient after external domain growth', all_values_and_old_generation=True)

# Multiple file-domain columns, and a tail whose independent domain interns
# its entries in a different order. Check values, null masks and stale index.
root = out / 'multiple-independent-domain'
root.mkdir()
table, sym = root/'table', root/'.sym'
tail_table, tail_sym = root/'tail', root/'.tail-sym'
initial = '(table [a b] (list (.idx.hash (as \'SYMBOL ["red" "blue" ""])) (as \'SYMBOL ["bee" "red" ""])))'
tail = '(table [a b] (list (as \'SYMBOL ["bee" "fresh" ""]) (as \'SYMBOL ["fresh" "blue" ""])))'
ok(f'(.db.splayed.set "{table}" {initial} "{sym}" {{compress: false}})\n'
   f'(.db.splayed.set "{table}" {initial} "{sym}" {{compress: false}})\n'
   f'(.db.splayed.set "{tail_table}" {tail} "{tail_sym}" {{compress: false}})')
prior = current(table)
before = dump(table, sym, 'multiple-before')
tail_rows = dump(tail_table, tail_sym, 'multiple-tail')
assert 'INDEX true' in ok(f'(set a (.db.splayed.get "{table}" "{sym}"))\n(println "INDEX" (.idx.has? (at a \'a)))')
ok(f'(set t (.db.splayed.get "{tail_table}" "{tail_sym}"))\n'
   f'(.db.splayed.append "{table}" t "{sym}")')
assert dump(table, sym, 'multiple-after') == before + tail_rows[1:]
assert dump(prior, sym, 'multiple-prior') == before
assert 'INDEX false false' in ok(f'(set a (.db.splayed.get "{table}" "{sym}"))\n'
                                '(println "INDEX" (.idx.has? (at a \'a)) (.idx.has? (at a \'b)))')
record('multiple file domains remapped, nulls, preserved generation, removed index')


if fault_binary:
    # Every case has a narrow SYM column and a fresh symbol; pre-publication
    # failures keep the active and retained generation unchanged. Faults
    # after publication report `commit` and expose the complete new table.
    for point in ('clone-0', 'column-0', 'manifest', 'publish', 'directory'):
        root, table, sym, prior = seed_single('fail-' + point, 3)
        before = dump(table, sym, 'fail-' + point + '-before')
        p = run(append_expr(table, sym, ['fresh', 's0']), fault_binary,
                {'RAY_APPEND_FAIL': point})
        post = point in ('publish', 'directory')
        assert p.returncode != 0 and f'error: {"commit" if post else "io"}' in p.stdout+p.stderr
        assert dump(prior, sym, 'fail-' + point + '-old') == before
        assert dump(table, sym, 'fail-' + point + '-active') == before + ([['fresh'], ['s0']] if post else [])
        record('fault at ' + point, expected_code='commit' if post else 'io')

    for point in ('column-0', 'manifest', 'publish', 'directory'):
        root, table, sym, prior = seed_single('kill-' + point, 3)
        before = dump(table, sym, 'kill-' + point + '-before')
        p = run(append_expr(table, sym, ['fresh', 's0']), fault_binary,
                {'RAY_APPEND_STOP': point}, asynchronous=True)
        try:
            end = time.monotonic() + 30
            stopped = False
            while time.monotonic() < end:
                pid, status = os.waitpid(p.pid, os.WUNTRACED | os.WNOHANG)
                if pid:
                    stopped = os.WIFSTOPPED(status) and os.WSTOPSIG(status) == signal.SIGSTOP
                    break
                time.sleep(.01)
            assert stopped, ('checkpoint not reached', point)
            os.kill(p.pid, signal.SIGKILL)
            p.communicate(timeout=10)
            assert p.returncode == -signal.SIGKILL
            post = point in ('publish', 'directory')
            assert dump(prior, sym, 'kill-' + point + '-old') == before
            assert dump(table, sym, 'kill-' + point + '-active') == before + ([['fresh'], ['s0']] if post else [])
            record('SIGKILL after ' + point)
        finally:
            if p.poll() is None:
                p.kill(); p.wait()
else:
    print('DEBUG fault and SIGKILL tests skipped: no optimized debug binary', flush=True)

print('S0 independent checks passed:', len(records), flush=True)
