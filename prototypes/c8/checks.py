#!/usr/bin/env python3
"""Restricted IPC contract: typed tables, denial controls, same-connection visibility."""
import csv, datetime, hashlib, importlib.util, json, os, re, secrets, signal, socket, struct, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BINARY=Path(sys.argv[1]).resolve(); OUT=Path(sys.argv[2]).resolve();OUT.mkdir(parents=True,exist_ok=False)
qspec=importlib.util.spec_from_file_location('wire','/home/gunazzi/Northline-Terminal/.scratch/agent-r0-31/proto/rayforce/scripts/run_queries.py')
q=importlib.util.module_from_spec(qspec);qspec.loader.exec_module(q)
DATE='2026.10.29'; DAYS=(datetime.date(2026,10,29)-datetime.date(2000,1,1)).days
NAMES='instrument_id ts_recv ts_event bid_px ask_px bid_sz ask_sz raw_symbol parent'.split()
TAGS=[5,10,10,5,5,5,5,13,12]
def atom(tag,data): return struct.pack('bB',-tag,0)+data
def sym(name): return atom(12,name.encode()+b'\0')
def vector(tag,values):
    data=bytearray(bytes([tag,0])+struct.pack('<q',len(values)))
    for v in values:
        if tag==12: data+=v.encode()+b'\0'
        elif tag==13:
            b=v.encode();data+=struct.pack('<q',len(b))+b
        else: data+=struct.pack('<q',v)
    return bytes(data)
def table_bytes(columns):
    return bytes([98,0])+vector(12,NAMES)+bytes([0,0])+struct.pack('<q',9)+b''.join(vector(t,c) for t,c in zip(TAGS,columns))
def request(table,date=DAYS):
    return bytes([0,0])+struct.pack('<q',3)+sym('.db.append_today')+table+atom(8,struct.pack('<i',date))
def exchange(client,payload):
    client.sock.sendall(q.HEADER.pack(q.PREFIX,3,0,0,1,len(payload))+payload)
    magic,version,flags,endian,kind,size=q.HEADER.unpack(client.exact(16))
    assert (magic,version,flags,endian,kind)==(q.PREFIX,3,0,0,2)
    return q.decode(client.exact(size))
def run(text,label):
    path=OUT/f'{label}.rfl';path.write_text(text+'\n')
    p=subprocess.run([str(BINARY),'-c','2','-f',str(path)],capture_output=True,text=True,timeout=60)
    (OUT/f'{label}.log').write_text(p.stdout+p.stderr)
    assert p.returncode==0 and 'error:' not in p.stdout+p.stderr,(p.stdout,p.stderr)

base=OUT/'db'; table=base/DATE/'quotes_1m'; symbol=base/'.sym'
old='(table ['+' '.join(NAMES)+'] (list [1 2] (as \'TIMESTAMP [123 0N]) (as \'TIMESTAMP [0N 234]) [10 20] [11 21] [2 3] [4 5] (as \'STR ["short" "a long raw option symbol"]) (as \'SYMBOL ["AAA" "BBB"])))'
run(f'(.db.splayed.set "{table}" {old} "{symbol}" {{compress: false}})','seed')
fixture=Path('/home/gunazzi/lead-linux/rayforce-prototypes/c2/fixture/tail.csv')
columns=[[] for _ in NAMES]
with fixture.open() as f:
    for row in csv.DictReader(f):
        for i,(name,tag) in enumerate(zip(NAMES,TAGS)):
            v=row[name]
            if tag in (5,10):
                v=int(v) if v else -(2**63)
                if tag==10 and v!=-(2**63):v-=946684800000000000
            columns[i].append(v)
payload=table_bytes(columns)
(OUT/'minute.table').write_bytes(payload)
packet=request(payload);(OUT/'minute.request').write_bytes(packet)
launch=OUT/'launch.rfl';launch.write_text(f'(set held (.db.parted.get "{base}" \'quotes_1m))\n')
denied=[]
def start(extra,env_extra=None):
    port=q.free_port();password=secrets.token_urlsafe(24)
    log=(OUT/f'server-{port}.log').open('wb')
    env=os.environ.copy();env.update(env_extra or {})
    p=subprocess.Popen([str(BINARY),'-c','4','-f',str(launch),'--port',f'127.0.0.1:{port}','-U',password,*extra],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        if p.poll() is not None:log.close();raise AssertionError('server failed launch')
        try:return p,log,q.Client(port,password)
        except ConnectionError:time.sleep(.02)
    p.kill();p.wait();log.close();raise AssertionError('no server')
def stop(p,log,c):
    c.close();p.terminate();p.wait(timeout=10);log.close()

p,log,c=start(['--append-root',str(base),'--append-date',DATE])
try:
    assert c.evaluate('(count quotes_1m)')==2
    denied_text=[('set','(set malicious 1)'),('bind function','(set malicious (fn [] 1))'),
        ('exec',f'(.sys.exec "touch {OUT}/exec-escaped")'),('exit','(exit 7)'),
        ('read',f'(read "{launch}")'),('read-bytes',f'(read-bytes "{launch}")'),
        ('write',f'(write "{OUT}/write-escaped" "x")'),
        ('write-bytes',f'(write-bytes "{OUT}/write-escaped" [1 2])'),
        ('other root',f'(.db.splayed.append "{OUT}/other" {old} "{symbol}")'),
        ('other partition',f'(.db.splayed.set "{base}/2026.10.28/quotes_1m" {old} "{symbol}")'),
        ('past date',f'(.db.append_today {old} 2026.10.28)'),
        ('future date',f'(.db.append_today {old} 2026.10.30)'),
        ('path argument',f'(.db.append_today {old} {DATE} "{OUT}/other")'),
        ('path as table',f'(.db.append_today "{OUT}/other" {DATE})'),
        ('indirect exec',f'((resolve (quote .sys.exec)) "touch {OUT}/indirect-escaped")')]
    for label,text in denied_text:
        result=c.evaluate(text);assert result=={'error':'access'},(label,result)
        denied.append(dict(call=label,answer='access'))
    result=exchange(c,packet);assert result==2+len(columns[0]),result
    assert c.evaluate('(count quotes_1m)')==2+len(columns[0])
    assert c.evaluate('(count held)')==2
    returned=c.evaluate('(select {'+' '.join(f'{n}: {n}' for n in NAMES)+' from: quotes_1m where: (> instrument_id 2)})')
    assert returned=={'table':dict(zip(NAMES,columns))},'every field in the appended real minute must match'
    assert c.evaluate('(set still_denied 1)')=={'error':'access'}
    assert c.evaluate('(+ 1 2)')==3
    # Existing database reads are NOT a filesystem sandbox: show the positive
    # control rather than claim generic file denial covers these entry points.
    assert c.evaluate(f'(count (.db.splayed.get "{table}" "{symbol}"))')==2+len(columns[0])
    for marker in ('exec-escaped','write-escaped','indirect-escaped'):assert not (OUT/marker).exists()
finally:stop(p,log,c)
p,log,c=start([])
try:
    assert exchange(c,packet)=={'error':'access'}
    assert c.evaluate(f'(count (.db.splayed.get "{table}" "{symbol}"))')==2+len(columns[0])
    c.sock.sendall(q.HEADER.pack(q.PREFIX,3,0,0,1,256*1024*1024+1))
    assert c.sock.recv(1)==b'', 'oversize header must close before allocating its body'
finally:stop(p,log,c)

# Force failure after durable publication but before the capability remount.
# The debug checkpoint proves that the mutation actually reached this point.
p,log,c=start(['--append-root',str(base),'--append-date',DATE],{'RAY_APPEND_STOP':'directory'})
away=OUT/'temporarily-moved-root'
try:
    c.sock.sendall(q.HEADER.pack(q.PREFIX,3,0,0,1,len(packet))+packet)
    deadline=time.monotonic()+20;stopped=False
    while time.monotonic()<deadline:
        pid,status=os.waitpid(p.pid,os.WUNTRACED|os.WNOHANG)
        if pid:
            stopped=os.WIFSTOPPED(status) and os.WSTOPSIG(status)==signal.SIGSTOP;break
        time.sleep(.01)
    assert stopped, 'post-publish checkpoint must execute'
    base.rename(away);os.kill(p.pid,signal.SIGCONT)
    header=q.HEADER.unpack(c.exact(16));result=q.decode(c.exact(header[-1]))
    assert result=={'error':'commit'},result
    away.rename(base)
    assert c.evaluate('(count quotes_1m)')==2+len(columns[0]), 'failed remount retains old binding'
    assert c.evaluate(f'(count (.db.splayed.get "{table}" "{symbol}"))')==2+2*len(columns[0])
    assert c.evaluate('(set after_commit 1)')=={'error':'access'}
finally:
    if away.exists():away.rename(base)
    if p.poll() is None:os.kill(p.pid,signal.SIGCONT)
    stop(p,log,c)

# A partition symlink is a concrete root-escape counterexample.
escape=OUT/'escape';escape.mkdir();(escape/'.sym').symlink_to(symbol)
(escape/DATE).symlink_to(base/DATE,target_is_directory=True)
port=q.free_port()
p=subprocess.run([str(BINARY),'-c','2','--port',f'127.0.0.1:{port}','-U','fixture-only','--append-root',str(escape),'--append-date',DATE],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=20)
assert p.returncode!=0 and 'configuration refused' in p.stderr

# Freeze and check the exact restriction surface and unchanged request/host hook.
before=subprocess.check_output(['git','show','3a96cc0a:src/lang/eval.c'],cwd=ROOT,text=True)
after=(ROOT/'src/lang/eval.c').read_text()
restricted=lambda text:re.findall(r'register_\w+\s*\(\s*"([^"]+)"[^;]*RAY_FN_RESTRICTED[^;]*;',text)
assert restricted(before)==restricted(after)
assert not subprocess.check_output(['git','diff','3a96cc0a','--','src/core/ipc.c','src/lang/env.c','src/lang/syscmd.c','src/ops/system.c'],cwd=ROOT)
assert 'ray_eval_set_restricted' not in (ROOT/'src/store/appendcap.c').read_text()
(OUT/'restricted-list.json').write_text(json.dumps(dict(before=restricted(before),after=restricted(after)),indent=2)+'\n')
summary=dict(binary=str(BINARY),sha256=hashlib.sha256(BINARY.read_bytes()).hexdigest(),denials=denied,minute_rows=len(columns[0]),request_bytes=len(packet),frame_cap_bytes=256*1024*1024,same_connection_visible=True,held_snapshot_unchanged=True,all_fields_equal=True,disabled_denied=True,escape_launch_denied=True,baseline_database_read_allowed=True,oversize_header_rejected=True,post_publish_mount_failure_commit=True,restricted_list_unchanged=True)
(OUT/'results.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
