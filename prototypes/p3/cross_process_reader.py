#!/usr/bin/env python3
"""Hold an mmap-backed reader open across another process's append."""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

binary = Path(sys.argv[1]).resolve()
fixture_home = Path('/home/gunazzi/lead-linux/rayforce-prototypes/p3')
with tempfile.TemporaryDirectory(prefix='reader-cross-process-', dir=fixture_home) as td:
    d = Path(td)
    table, ready, done = d / 'table', d / 'ready', d / 'done'
    setup = d / 'setup.rfl'
    setup.write_text(f'''(.db.splayed.set "{table}" (table [id ts] (list [1 2] (as 'TIMESTAMP [123 0N]))) {{compress: false}})
''')
    reader_file = d / 'reader.rfl'
    reader_file.write_text(f'''(set old (.db.splayed.get "{table}"))
(println "BEFORE" (count old) (sum (at old 'id)) (nil? (at (at old 'ts) 1)))
(.sys.exec "touch '{ready}'; while [ ! -e '{done}' ]; do sleep .05; done")
(println "AFTER" (count old) (sum (at old 'id)) (nil? (at (at old 'ts) 1)))
''')
    writer_file = d / 'writer.rfl'
    writer_file.write_text(f'''(.db.splayed.append_proto "{table}" (table [id ts] (list [3 4] (as 'TIMESTAMP [456 789]))))
(set now (.db.splayed.get "{table}"))
(println "NEW" (count now) (sum (at now 'id)) (nil? (at (at now 'ts) 1)))
''')
    subprocess.run([str(binary), '-f', str(setup)], check=True, capture_output=True, text=True, timeout=30)
    reader = subprocess.Popen([str(binary), '-f', str(reader_file)], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline and reader.poll() is None:
            time.sleep(.02)
        if not ready.exists():
            raise RuntimeError('reader did not confirm it mapped the old table')
        writer = subprocess.run([str(binary), '-f', str(writer_file)], check=True,
                                capture_output=True, text=True, timeout=30)
        if 'NEW 4 10 true' not in writer.stdout:
            raise AssertionError(writer.stdout)
        done.touch()
        stdout, stderr = reader.communicate(timeout=30)
        if reader.returncode or 'BEFORE 2 3 true' not in stdout or 'AFTER 2 3 true' not in stdout:
            raise AssertionError((reader.returncode, stdout, stderr))
        print('PASS: a separate process retained its old mmap view across publication')
        print(stdout.strip())
        print(writer.stdout.strip())
        writers = []
        for value in (5, 6):
            script = d / f'writer-{value}.rfl'
            script.write_text(f'''(.db.splayed.append_proto "{table}" (table [id ts] (list [{value}] (as 'TIMESTAMP [{value * 100}]))))
''')
            writers.append(subprocess.Popen([str(binary), '-f', str(script)], stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, text=True))
        try:
            for child in writers:
                out, err = child.communicate(timeout=30)
                if child.returncode:
                    raise RuntimeError(('concurrent append failed', child.returncode, out, err))
        finally:
            for child in writers:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
        verify = d / 'verify.rfl'
        verify.write_text(f'''(set t (.db.splayed.get "{table}"))
(println "WRITERS" (count t) (sum (at t 'id)))
''')
        final = subprocess.run([str(binary), '-f', str(verify)], check=True,
                               capture_output=True, text=True, timeout=30)
        if 'WRITERS 6 21' not in final.stdout:
            raise AssertionError(final.stdout)
        print('PASS: two concurrent writer processes both published their rows')
        print(final.stdout.strip())
    finally:
        done.touch(exist_ok=True)
        if reader.poll() is None:
            reader.terminate()
            reader.wait(timeout=5)
