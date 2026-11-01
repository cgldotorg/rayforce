#!/usr/bin/env python3
"""Contract counterexamples, using disposable roots and independent processes."""
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import time

BINARY = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
OUT.mkdir(parents=True, exist_ok=False)
NAMES = 'instrument_id ts_recv ts_event bid_px ask_px bid_sz ask_sz raw_symbol parent'.split()
TYPES = '[I64 TIMESTAMP TIMESTAMP I64 I64 I64 I64 STR SYMBOL]'
old = '(table ['+' '.join(NAMES)+'] (list (.idx.hash [1 2]) (as \'TIMESTAMP [123 0N]) (as \'TIMESTAMP [0N 234]) [10 20] [11 21] [2 3] [4 5] (as \'STR ["short" "a long raw option symbol"]) (as \'SYMBOL ["AAA" "BBB"])))'
add = '(table ['+' '.join(NAMES)+'] (list [3 4] (as \'TIMESTAMP [345 456]) (as \'TIMESTAMP [567 0N]) [30 40] [31 41] [6 7] [8 9] (as \'STR ["" "another very long option symbol"]) (as \'SYMBOL ["CCC" "AAA"])))'
records = []
serial = 0

def script(text, extra=None, async_=False):
    global serial
    serial += 1
    p = OUT / f'case-{serial}.rfl'
    p.write_text(text+'\n')
    env = os.environ.copy()
    env.update(extra or {})
    cmd = [str(BINARY), '-c', '2', '-f', str(p)]
    if async_:
        return subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
    (OUT/f'case-{serial}.log').write_text(r.stdout+r.stderr)
    return r

def ok(text):
    r = script(text)
    assert r.returncode == 0 and 'error:' not in r.stdout+r.stderr, (text,r.stdout,r.stderr)
    return r.stdout

def seed(label):
    root=OUT/label; root.mkdir()
    table=root/'table'; sym=root/'.sym'
    ok(f'(.db.splayed.set "{table}" {old} "{sym}" {{compress: false}})\n'
       f'(.db.splayed.set "{table}" {old} "{sym}" {{compress: false}})')
    gen=table/(table/'.current').read_text().strip()
    return root,table,sym,gen

def dump(table,sym,label):
    dest=OUT/f'{label}.csv'
    ok(f'(.csv.write (.db.splayed.get "{table}" "{sym}") "{dest}")')
    with dest.open() as f: return list(csv.reader(f))

def append(table,sym,tail=add):
    return f'(.db.splayed.append "{table}" {tail} "{sym}")'

def record(name, **extra):
    records.append(dict(test=name,status='pass',**extra))
    (OUT/'results.json').write_text(json.dumps(dict(binary=str(BINARY),sha256=hashlib.sha256(BINARY.read_bytes()).hexdigest(),tests=records),indent=2)+'\n')
    print('PASS',name,flush=True)

# A positive success control establishes every expected appended field.
root,table,sym,gen=seed('success')
before=dump(table,sym,'expected-old')
tailtable=root/'tail'
ok(f'(.db.splayed.set "{tailtable}" {add} "{sym}" {{compress: false}})')
tail=dump(tailtable,sym,'expected-tail')
expected=before+tail[1:]
ok(append(table,sym))
assert dump(table,sym,'success-current') == expected
assert dump(gen,sym,'success-old') == before
assert 'INDEX false false false false false false false false false' in ok(
    f'(set t (.db.splayed.get "{table}" "{sym}"))\n'
    '(println "INDEX" '+ ' '.join(f"(.idx.has? (at t '{c}))" for c in NAMES)+')')
record('nine fields, nulls, strings, symbols, old generation and index removal')

points=['chain','sym']+[f'column-{i}' for i in range(9)]+['schema','generation','parent','manifest','publish','directory']
for point in points:
    root,table,sym,gen=seed('kill-'+point)
    child=script(append(table,sym),{'RAY_APPEND_STOP':point},True)
    try:
        deadline=time.monotonic()+20
        stopped=False
        while time.monotonic()<deadline:
            pid,status=os.waitpid(child.pid,os.WUNTRACED|os.WNOHANG)
            if pid:
                stopped=os.WIFSTOPPED(status) and os.WSTOPSIG(status)==signal.SIGSTOP
                break
            time.sleep(.01)
        assert stopped, ('checkpoint did not execute',point)
        os.kill(child.pid,signal.SIGKILL)
        child.communicate(timeout=10)
        assert child.returncode == -signal.SIGKILL
        assert dump(gen,sym,'k-old-'+point)==before
        assert dump(table,sym,'k-new-'+point)==(expected if point in ('publish','directory') else before)
        record('SIGKILL after '+point)
    finally:
        if child.poll() is None: child.kill(); child.wait()

for point in points+[f'clone-{i}' for i in range(9)]:
    root,table,sym,gen=seed('fail-'+point)
    r=script(append(table,sym),{'RAY_APPEND_FAIL':point})
    post=point in ('publish','directory')
    code='commit' if post else 'io'
    assert r.returncode != 0 and f'error: {code}' in r.stdout+r.stderr,(point,r.stdout,r.stderr)
    assert dump(gen,sym,'f-old-'+point)==before
    assert dump(table,sym,'f-new-'+point)==(expected if post else before)
    record('I/O failure at '+point, expected_code=code)

root,table,sym,gen=seed('reader-writers')
ready=root/'ready'; done=root/'done'; held_csv=root/'held.csv'
reader=script(f'(set held (.db.splayed.get "{table}" "{sym}"))\n'
              f'(.sys.exec "touch {ready}; while [ ! -e {done} ]; do sleep .02; done")\n'
              f'(.csv.write held "{held_csv}")',async_=True)
try:
    deadline=time.monotonic()+15
    while not ready.exists() and time.monotonic()<deadline: time.sleep(.01)
    assert ready.exists()
    writers=[script(append(table,sym,add.replace('CCC',f'NEW{i}')),async_=True) for i in range(2)]
    for w in writers:
        out,err=w.communicate(timeout=30)
        assert w.returncode==0 and 'error:' not in out+err,(out,err)
    done.touch(); out,err=reader.communicate(timeout=30)
    assert reader.returncode==0,(out,err)
    with held_csv.open() as f: assert list(csv.reader(f))==before
    data=dump(table,sym,'two-writers')
    assert data[:3]==before and len(data)==7
    assert sorted(data[3:])==sorted([row[:-1]+(['NEW0'] if row[-1]=='CCC' else [row[-1]]) for row in tail[1:]]+[row[:-1]+(['NEW1'] if row[-1]=='CCC' else [row[-1]]) for row in tail[1:]])
    record('held separate process and two concurrent writers with distinct symbols')
finally:
    done.touch()
    if reader.poll() is None: reader.kill(); reader.wait()

for count,width in [(254,0),(65534,1)]:
    root=OUT/f'width-{count}'; root.mkdir(); table=root/'table'; sym=root/'.sym'
    src=root/'symbols.csv'
    with src.open('w') as f:
        w=csv.writer(f); w.writerow(['s']); w.writerows([[f's{i}'] for i in range(count)])
    ok(f'(.db.splayed.set "{table}" (.csv.read [SYMBOL] "{src}") "{sym}" {{compress: false}})')
    assert (table/'s').read_bytes()[19]&3==width
    extra='(table [s] (list (as \'SYMBOL ["new one" "new two"])))'
    ok(append(table,sym,extra))
    new=table/(table/'.current').read_text().strip()
    assert (new/'s').read_bytes()[19]&3==2
    data=dump(table,sym,f'width-{count}')
    assert data==[['s']]+[[f's{i}'] for i in range(count)]+[['new one'],['new two']]
    record(f'symbol width boundary {count+1} to {count+3}, every cell')

root,table,sym,gen=seed('rejections')
for label,tail_,code in [('late name',add.replace('raw_symbol parent','raw_symbol wrong'),'type'),
                         ('late type',add.replace("(as 'SYMBOL", "(as 'STR"),'type'),
                         ('linked tail',add.replace('[3 4]',"(.col.link 'dim [3 4])"),'domain')]:
    r=script('(set dim (table [x] (list [0 1 2 3 4])))\n'+append(table,sym,tail_))
    assert r.returncode!=0 and f'error: {code}' in r.stdout+r.stderr,(label,r.stdout,r.stderr)
    assert dump(table,sym,label.replace(' ','-'))==before
    record('reject '+label)
ok(f'(.db.splayed.set "{table}" {old} "{sym}" {{compress: true}})')
r=script(append(table,sym)); assert r.returncode!=0 and 'error: domain' in r.stdout+r.stderr
assert dump(table,sym,'compressed-rejected')==before
record('compressed storage rejected')

# A sparse, format-valid old pool at the 32-bit limit exercises the owning
# append API without allocating or writing four GiB of physical payload.
root,table,sym,gen=seed('pool-overflow')
path=gen/'raw_symbol'
with path.open('r+b') as f:
    f.seek(0); f.write(b'\0'*4)  # no index trailer
    f.seek(32+2*16+24); f.write(struct.pack('<q',2**32-1))
    f.truncate(32+2*16+32+(2**32-1))
prior=(table/'.current').read_bytes()
r=script(append(table,sym))
assert r.returncode!=0 and 'error: range' in r.stdout+r.stderr,(r.stdout,r.stderr)
assert (table/'.current').read_bytes()==prior
assert dump(table,sym,'overflow-unchanged')==before
path.unlink()  # release the sparse mapping fixture promptly
record('32-bit STR pool overflow rejects without publication')
print('ALL CONTRACT CHECKS PASSED',flush=True)
