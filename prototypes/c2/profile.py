#!/usr/bin/env python3
"""Untimed relative to the reported measurements: sample one complete append."""
import subprocess, sys
from pathlib import Path
binary=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();out.mkdir(parents=True,exist_ok=False)
fix=Path('/home/gunazzi/lead-linux/rayforce-prototypes/c2/fixture');root=out/'db'
subprocess.run(['cp','-a','--reflink=always',str(fix/'base'),str(root)],check=True)
for file in root.rglob('*'):
    if file.is_file():
        with file.open('rb') as f:
            while f.read(4*1024*1024):pass
script=out/'append.rfl'
script.write_text(f'(set tail (.db.splayed.get "{fix}/tail" "{root}/.sym"))\n(println (.db.splayed.append "{root}/2026.10.29/quotes_1m" tail "{root}/.sym"))\n')
with (out/'process.log').open('w') as log:
    subprocess.run(['/usr/bin/time','-v','perf','record','-F','997','-g','-o',str(out/'perf.data'),'--',str(binary),'-c','16','-f',str(script)],stdout=log,stderr=log,check=True)
with (out/'perf-report.txt').open('w') as log:
    subprocess.run(['perf','report','--stdio','--no-children','--percent-limit','1','-i',str(out/'perf.data')],stdout=log,stderr=log,check=True)
