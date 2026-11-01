#!/usr/bin/env python3
"""A sorted prefix plus an out-of-order tail must lose its sorted metadata."""
import subprocess,sys
from pathlib import Path
binary=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();out.mkdir(exist_ok=False)
table=out/'table';sym=out/'.sym'
def run(source,name):
 p=out/(name+'.rfl');p.write_text(source+'\n')
 r=subprocess.run([str(binary),'-c','2','-f',str(p)],capture_output=True,text=True)
 (out/(name+'.log')).write_text(r.stdout+r.stderr)
 assert r.returncode==0 and 'error:' not in r.stdout+r.stderr,(r.stdout,r.stderr)
 return r.stdout
run(f'(.db.splayed.set "{table}" (table [x s] (list (.attr.set \'sorted [1 2]) (as \'SYMBOL ["A" "A"]))) "{sym}" {{compress: false}})','seed')
assert (table/'x').read_bytes()[19]&0x20, 'positive control: persisted sorted prefix'
run(f'(.db.splayed.append "{table}" (table [x s] (list [0] (as \'SYMBOL ["B"]))) "{sym}")','append')
gen=table/(table/'.current').read_text().strip()
assert not (gen/'x').read_bytes()[19]&0x20, 'new metadata must not promise sorted values'
assert 'SORT_VERIFIED' in run(f'(set t (.db.splayed.get "{table}" "{sym}"))\n(if (not (all (== (asc (at t \'x)) [0 1 2]))) (raise "sort mismatch"))\n(println "SORT_VERIFIED")','verify')
print('PASS: sorted prefix + out-of-order tail; metadata and ordered answer')
