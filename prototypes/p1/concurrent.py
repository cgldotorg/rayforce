#!/usr/bin/env python3
"""Bounded cross-process shared-symbol race probe; success paths are reread."""
from pathlib import Path
import subprocess
import sys
import tempfile

binary, workspace = (Path(p).resolve() for p in sys.argv[1:3])
with tempfile.TemporaryDirectory(prefix='sym-race-', dir=workspace) as tmp:
    home = Path(tmp)
    seed = home / 'seed.rfl'
    seed.write_text('''(set a (at (.sys.args) 'user))
(set db (at a 'db))
(.db.splayed.set (format "%/2026.01.01/quotes" db) (table [id parent] (list [0] ['seed])) (format "%/.sym" db))
''')
    write = home / 'write.rfl'
    write.write_text('''(set a (at (.sys.args) 'user))
(set db (at a 'db))
(set sym (format "%/.sym" db))
(count (.csv.splayed (dict [sym_path durable] (list sym true)) [I64 SYMBOL] (at a 'csv) (format "%/%/quotes" db (at a 'day))))
''')
    check = home / 'check.rfl'
    check.write_text('''(set a (at (.sys.args) 'user))
(set db (at a 'db))
(set q (.db.splayed.get (format "%/%/quotes" db (at a 'day)) (format "%/.sym" db)))
(set raw (.csv.read [I64 SYMBOL] (at a 'csv)))
(if (not (== (count q) (count raw))) (raise "count mismatch"))
(if (not (all (== (at q 'id) (at raw 'id)))) (raise "id mismatch"))
(if (not (all (== (at q 'parent) (at raw 'parent)))) (raise "symbol mismatch"))
(println "checked" (count q))
''')
    for trial in range(1, 5):
        db = home / str(trial)
        db.mkdir()
        start = subprocess.run([str(binary), '-f', str(seed), '--', '-db', str(db)],
                               capture_output=True, text=True, timeout=60)
        if start.returncode: raise RuntimeError(start.stderr)
        children = []
        cases = []
        for i, day in enumerate(('2026.01.02', '2026.01.03')):
            csv = home / f'{trial}-{i}.csv'
            with csv.open('w') as f:
                f.write('id,parent\n')
                for row in range(10000): f.write(f'{row},{i}-{row}\n')
            cmd = [str(binary), '-c', '4', '-f', str(write), '--', '-db', str(db),
                   '-csv', str(csv), '-day', day]
            children.append(subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            cases.append((day, csv))
        outcomes = [child.communicate(timeout=120) for child in children]
        states = []
        for child, (stdout, stderr), (day, csv) in zip(children, outcomes, cases):
            if child.returncode == 0:
                verified = subprocess.run([str(binary), '-c', '4', '-f', str(check), '--', '-db', str(db),
                                           '-csv', str(csv), '-day', day], capture_output=True, text=True, timeout=120)
                if verified.returncode or 'checked 10000' not in verified.stdout:
                    raise RuntimeError(f'published output mismatch: {verified.stdout} {verified.stderr}')
                states.append('success-and-matched')
            else:
                if (db / day / 'quotes' / '.d').exists() or (db / day / 'quotes' / '.current').exists():
                    raise RuntimeError(f'failed writer published: {stderr}')
                states.append('failed-without-publication:' + stderr.strip().replace('\n', ' '))
        seed_csv = home / f'{trial}-seed.csv'
        seed_csv.write_text('id,parent\n0,seed\n')
        verified = subprocess.run([str(binary), '-f', str(check), '--', '-db', str(db), '-csv', str(seed_csv),
                                   '-day', '2026.01.01'], capture_output=True, text=True, timeout=120)
        if verified.returncode or 'checked 1' not in verified.stdout: raise RuntimeError(verified.stderr)
        print(f'trial {trial}: {states}; seed matched', flush=True)
