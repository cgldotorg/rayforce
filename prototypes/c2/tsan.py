#!/usr/bin/env python3
import json, os, re, subprocess, sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(); out=Path(sys.argv[2]).resolve(); out.mkdir(exist_ok=True)
env=os.environ.copy()
env['RAYFORCE_CORES']='4'
scratch=out/'scratch';scratch.mkdir(exist_ok=True)
env['RAY_TEST_TMPDIR']=str(scratch)
env['TSAN_OPTIONS']=f'suppressions={root}/.tsan-suppressions history_size=7 second_deadlock_stack=1 halt_on_error=1'
os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:4])
results=[]
for name in ['product_schema_append','pool','heap','parallel','stress','parted_concurrent_mounts']:
    p=subprocess.run([str(root/'rayforce.test.tsan'),'-f',name],cwd=root,env=env,capture_output=True,text=True,timeout=600)
    log=p.stdout+p.stderr;(out/f'{name}.log').write_text(log)
    summary=re.findall(r'=== (\d+) of (\d+) passed \((\d+) skipped, (\d+) failed\) ===',log)
    row=dict(filter=name,exit=p.returncode,summary=summary,warning='WARNING: ThreadSanitizer' in log,affinity=sorted(os.sched_getaffinity(0)))
    results.append(row);(out/'results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(row),flush=True)
    if p.returncode or not summary or any(int(s[3]) for s in summary) or row['warning']:
        raise SystemExit('TSan filter failed: '+name)
