#!/usr/bin/env python3
"""Exercise CSV import and append writers contending on one symbol domain.

Usage: mixed_writers.py DEBUG_RAYFORCE NEW_OUTPUT_DIRECTORY
The DEBUG executable must include the CSV and append stop checkpoints. Run on
a filesystem supporting FICLONE. Output is retained for inspection.
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


binary = Path(sys.argv[1]).resolve(strict=True)
out = Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=False)
serial = 0
records = []
old = '(table [id value parent] (list [1 2] [10 20] (as \'SYMBOL ["A" "B"])))'
tail = '(table [id value parent] (list [3 4] [30 40] (as \'SYMBOL ["APPEND_ONLY" "A"])))'
expected_append = [['id', 'value', 'parent'], ['1', '10', 'A'], ['2', '20', 'B'],
                   ['3', '30', 'APPEND_ONLY'], ['4', '40', 'A']]
expected_import = [['id', 'value', 'parent'], ['5', '50', 'IMPORT_ONLY'],
                   ['6', '60', 'B'], ['7', '70', 'IMPORT_ONLY']]
old_eight = ('(table [instrument_id ts_recv ts_event bid_px ask_px bid_sz ask_sz parent] '
             '(list [1 2] (as \'TIMESTAMP [123 456]) (as \'TIMESTAMP [0N 789]) '
             '[10 20] [11 21] [2 3] [4 5] (as \'SYMBOL ["A" "B"])))')
tail_eight = ('(table [instrument_id ts_recv ts_event bid_px ask_px bid_sz ask_sz parent] '
              '(list [3 4] (as \'TIMESTAMP [900 1000]) (as \'TIMESTAMP [1001 0N]) '
              '[30 40] [31 41] [6 7] [8 9] (as \'SYMBOL ["APPEND_ONLY" "A"])))')
csv_eight = ('(table [instrument_id ts_recv ts_event bid_px ask_px bid_sz ask_sz parent] '
             '(list [5 6 7] (as \'TIMESTAMP [1100 1200 1300]) '
             '(as \'TIMESTAMP [1400 0N 1600]) [50 60 70] [51 61 71] [10 11 12] '
             '[13 14 15] (as \'SYMBOL ["IMPORT_ONLY" "B" "IMPORT_ONLY"])))')


def quoted(path):
    return json.dumps(str(path))


def launch(text, extra=None):
    global serial
    serial += 1
    script = out / f'case-{serial:03}.rfl'
    script.write_text(text + '\n')
    env = os.environ.copy()
    # A caller's debug settings must not accidentally stop another writer.
    env.pop('RAY_CSV_SPLAYED_INJECT', None)
    env.pop('RAY_APPEND_STOP', None)
    env.pop('RAY_APPEND_FAIL', None)
    env.update(extra or {})
    child = subprocess.Popen([str(binary), '-c', '2', '-f', str(script)],
                             env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return child, serial


def finish(child, case, timeout=60):
    stdout, stderr = child.communicate(timeout=timeout)
    (out / f'case-{case:03}.log').write_text(stdout + '\n' + stderr)
    if child.returncode or 'error:' in stdout + stderr:
        raise AssertionError((case, child.returncode, stdout, stderr))
    return stdout


def sync(text):
    child, case = launch(text)
    return finish(child, case)


def await_stop(child, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pid, status = os.waitpid(child.pid, os.WUNTRACED | os.WNOHANG)
        if pid:
            if os.WIFSTOPPED(status) and os.WSTOPSIG(status) == signal.SIGSTOP:
                return
            raise AssertionError(('holder exited before stop', child.pid, status))
        time.sleep(.01)
    raise TimeoutError(f'writer {child.pid} did not hit its SIGSTOP checkpoint')


def await_flock_wait(child, lock_path, timeout=30):
    """Require an actual kernel-reported waiter for this .sym.lk inode."""
    inode = lock_path.stat().st_ino
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if child.poll() is not None:
            raise AssertionError(('contender exited rather than waiting', child.pid,
                                  child.returncode))
        try:
            tids = {int(p.name) for p in Path(f'/proc/{child.pid}/task').iterdir()}
        except FileNotFoundError as exc:
            raise AssertionError('contender disappeared') from exc
        for line in Path('/proc/locks').read_text().splitlines():
            fields = line.split()
            # A pending lock is marked '->'; match the caller thread and the
            # inode to avoid inferring contention merely from elapsed time.
            if '->' in fields and 'FLOCK' in fields and any(str(t) in fields for t in tids):
                if any(token.endswith(f':{inode}') for token in fields):
                    return line
        time.sleep(.01)
    raise TimeoutError(f'no FLOCK waiter observed for {lock_path}')


def dump(table, sym, name):
    path = out / f'{name}.csv'
    sync(f'(.csv.write (.db.splayed.get {quoted(table)} {quoted(sym)}) {quoted(path)})')
    with path.open(newline='') as f:
        return list(csv.reader(f))


for index, first in enumerate(('csv', 'append', 'append', 'csv', 'csv', 'append', 'csv', 'append'), 1):
    root = out / f'trial-{index}'
    root.mkdir()
    sym, table, imported = root / '.sym', root / 'append', root / 'import'
    source = root / 'import.csv'
    if index <= 4:
        old_table, tail_table = old, tail
        types = '[I64 I64 SYMBOL]'
        wanted_append, wanted_import = expected_append, expected_import
        source.write_text('id,value,parent\n5,50,IMPORT_ONLY\n6,60,B\n7,70,IMPORT_ONLY\n')
    else:
        old_table, tail_table = old_eight, tail_eight
        types = '[I64 TIMESTAMP TIMESTAMP I64 I64 I64 I64 SYMBOL]'
        old_csv, tail_csv = root / 'expected-old.csv', root / 'expected-tail.csv'
        sync(f'(.csv.write {old_table} {quoted(old_csv)})\n'
             f'(.csv.write {tail_table} {quoted(tail_csv)})\n'
             f'(.csv.write {csv_eight} {quoted(source)})')
        with old_csv.open(newline='') as f: old_rows = list(csv.reader(f))
        with tail_csv.open(newline='') as f: tail_rows = list(csv.reader(f))
        with source.open(newline='') as f: wanted_import = list(csv.reader(f))
        wanted_append = old_rows + tail_rows[1:]
    sync(f'(.db.splayed.set {quoted(table)} {old_table} {quoted(sym)} {{compress: false}})\n'
         f'(.db.splayed.set {quoted(table)} {old_table} {quoted(sym)} {{compress: false}})')
    append_sym = sym
    if index >= 7:
        append_sym = root / 'alias-sym'
        append_sym.symlink_to(sym.name)
    before_path = (table / '.current').read_text().strip()
    old_generation = table / before_path
    statements = {
        'append': f'(println "APPENDED" (.db.splayed.append {quoted(table)} {tail_table} {quoted(append_sym)}))',
        'csv': f'(println "IMPORTED" (count (.csv.splayed {{sym_path: {quoted(sym)} durable: true}} '
               f'{types} {quoted(source)} {quoted(imported)})))',
    }
    holder_env = {'csv': {'RAY_CSV_SPLAYED_INJECT': 'stop_after_sym'},
                  'append': {'RAY_APPEND_STOP': 'sym'}}[first]
    second = 'append' if first == 'csv' else 'csv'
    holder, holder_case = launch(statements[first], holder_env)
    contender = None
    try:
        await_stop(holder)
        contender, contender_case = launch(statements[second])
        lock_line = await_flock_wait(contender, root / '.sym.lk')
        # Keep the stopped owner alive while confirming the waiter is still
        # blocked, then release it and demand both successful results.
        if holder.poll() is not None or contender.poll() is not None:
            raise AssertionError('a writer exited while its peer held the lock')
        os.kill(holder.pid, signal.SIGCONT)
        first_out = finish(holder, holder_case)
        second_out = finish(contender, contender_case)
        outputs = {first: first_out, second: second_out}
        if 'APPENDED 4' not in outputs['append'] or 'IMPORTED 3' not in outputs['csv']:
            raise AssertionError(('unexpected writer answer', outputs))
        actual_append = dump(table, sym, f'trial-{index}-append')
        actual_import = dump(imported, sym, f'trial-{index}-import')
        actual_old = dump(old_generation, sym, f'trial-{index}-old')
        if actual_append != wanted_append or actual_import != wanted_import:
            raise AssertionError(('field mismatch', actual_append, actual_import))
        if actual_old != wanted_append[:3]:
            raise AssertionError(('old-generation mismatch', actual_old))
        record = {'trial': index, 'holder': first, 'waiter': second,
                  'columns': 3 if index <= 4 else 8,
                  'append_sym_is_symlink': index >= 7,
                  'kernel_waiter': lock_line, 'append_rows': 4, 'import_rows': 3,
                  'old_generation_rows': 2, 'field_and_symbol_equality': True}
        records.append(record)
        result = {'binary': str(binary), 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                  'affinity': sorted(os.sched_getaffinity(0)), 'workers_per_process': 2,
                  'load1': os.getloadavg()[0], 'cache': 'uncontrolled', 'trials': records}
        (out / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(record), flush=True)
    finally:
        for child in (holder, contender):
            if child is not None and child.poll() is None:
                child.kill()
                child.wait(timeout=10)

# A multiply linked symfile has no unique pathname for the lock identity and
# atomic domain replacement would detach aliases. Reject both writer paths.
root = out / 'hardlink-rejection'
root.mkdir()
sym, alias, table, imported = root / '.sym', root / 'hardlink', root / 'append', root / 'import'
source = root / 'import.csv'
source.write_text('id,value,parent\n5,50,IMPORT_ONLY\n6,60,B\n7,70,IMPORT_ONLY\n')
sync(f'(.db.splayed.set {quoted(table)} {old} {quoted(sym)} {{compress: false}})\n'
     f'(.db.splayed.set {quoted(table)} {old} {quoted(sym)} {{compress: false}})')
before = dump(table, sym, 'hardlink-before')
os.link(sym, alias)
for name, text in [
    ('append', f'(.db.splayed.append {quoted(table)} {tail} {quoted(alias)})'),
    ('csv', f'(.csv.splayed {{sym_path: {quoted(sym)} durable: true}} [I64 I64 SYMBOL] '
            f'{quoted(source)} {quoted(imported)})'),
]:
    child, case = launch(text)
    stdout, stderr = child.communicate(timeout=60)
    (out / f'case-{case:03}.log').write_text(stdout + '\n' + stderr)
    if child.returncode == 0 or 'error: reserve' not in stdout + stderr:
        raise AssertionError((name, child.returncode, stdout, stderr))
if dump(table, sym, 'hardlink-after') != before or (imported / '.d').exists():
    raise AssertionError('hardlink rejection changed persisted table')
record = {'test': 'multiply-linked symfile rejection', 'both_writers_rejected': True,
          'old_table_unchanged': True}
records.append(record)
result = {'binary': str(binary), 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
          'affinity': sorted(os.sched_getaffinity(0)), 'workers_per_process': 2,
          'load1': os.getloadavg()[0], 'cache': 'uncontrolled', 'trials': records}
(out / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(record), flush=True)
