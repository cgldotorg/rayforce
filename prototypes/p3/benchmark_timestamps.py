#!/usr/bin/env python3
"""Compare reflink append and rewrite of the same 11M-row timestamp fixture."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

binary, base, out = map(lambda s: Path(s).resolve(), sys.argv[1:4])
workers = int(sys.argv[4]) if len(sys.argv) > 4 else 8
scripts = Path(__file__).resolve().parent
out.mkdir(parents=True, exist_ok=False)
rows, tail = 11_000_000, 22_000
columns = ('instrument_id', 'ts_recv', 'ts_event', 'bid_px', 'ask_px', 'bid_sz', 'ask_sz')
samples = []
for rep in range(1, 4):
    for mode in (('append', 'rewrite') if rep != 2 else ('rewrite', 'append')):
        dest = out / f'{mode}-{rep}' / '2026.10.29' / 'quotes'
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['cp', '-a', '--reflink=always', str(base), str(dest)], check=True)
        rss = out / f'{mode}-{rep}.rss'
        cmd = ['/usr/bin/time', '-f', '%M', '-o', str(rss), str(binary), '-c', str(workers),
               '-f', str(scripts / f'{mode}_timestamps.rfl'), '--', '-root', str(dest)]
        load_before = os.getloadavg()
        start = time.monotonic()
        done = subprocess.run(cmd, text=True, capture_output=True, timeout=180)
        wall = time.monotonic() - start
        if done.returncode:
            raise RuntimeError((cmd, done.returncode, done.stdout, done.stderr))
        lines = done.stdout.splitlines()
        def vals(prefix):
            return [int(x) for x in next(s for s in lines if s.startswith(prefix + ' ')).split()[1:]]
        before, held, fresh, add = (vals(s) for s in ('BEFORE', 'HELD_AFTER', 'FRESH', 'TAIL'))
        if before != held or before[0] != rows or fresh[0] != rows + tail or add[0] != tail:
            raise AssertionError(done.stdout)
        if fresh[1] != before[1] + add[1] or fresh[2] != before[2] + add[2]:
            raise AssertionError(done.stdout)
        current = (dest / '.current').read_text().strip()
        published = dest / current
        for name in columns:
            with (base / name).open('rb') as original, (published / name).open('rb') as updated:
                original.seek(32); updated.seek(32)
                left = rows * 8
                while left:
                    n = min(left, 1024 * 1024)
                    a, b = original.read(n), updated.read(n)
                    if len(a) != n or a != b:
                        raise AssertionError(f'{name}: old payload differs')
                    left -= n
                original.seek(32)
                if original.read(tail * 8) != updated.read(tail * 8):
                    raise AssertionError(f'{name}: appended payload differs')
        timer = next(s for s in lines if s.startswith('APPEND_TIME '))
        match = re.search(r'time-ns:(\d+)', timer)
        if not match:
            raise AssertionError(timer)
        sample = dict(mode=mode, repeat=rep, engine_ms=int(match.group(1)) / 1e6,
                      process_s=wall, peak_rss_kib=int(rss.read_text().strip()),
                      load_before=load_before, load_after=os.getloadavg(), payloads_equal=True)
        samples.append(sample)
        print(json.dumps(sample), flush=True)
        result = dict(binary=str(binary), binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                      fixture=str(base), affinity=sorted(os.sched_getaffinity(0)), workers=workers,
                      rows=rows, tail=tail, samples=samples,
                      caveat='append drops indexes; rewrite rebuilds indexes')
        (out / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
