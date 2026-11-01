#!/usr/bin/env python3
"""Alternating typed and database-file-backed restricted appends of one minute."""
import hashlib, importlib.util, json, os, secrets, struct, subprocess, sys, time
from pathlib import Path
BINARY=Path(sys.argv[1]).resolve();OUT=Path(sys.argv[2]).resolve();OUT.mkdir(parents=True,exist_ok=False)
FIX=Path('/home/gunazzi/lead-linux/rayforce-prototypes/c2/fixture')
wire=Path('/home/gunazzi/lead-linux/rayforce-prototypes/c8/checks-2')
spec=importlib.util.spec_from_file_location('q','/home/gunazzi/Northline-Terminal/.scratch/agent-r0-31/proto/rayforce/scripts/run_queries.py');q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
packet=(wire/'minute.request').read_bytes();columns=q.decode((wire/'minute.table').read_bytes())['table'];names=list(columns)
meta=json.loads((FIX/'metadata.json').read_text());before=meta['rows']['base'];after=sum(meta['rows'].values());samples=[]
def rss(pid):
    return int(next(x for x in Path(f'/proc/{pid}/status').read_text().splitlines() if x.startswith('VmHWM:')).split()[1])
for rep in range(3):
    for mode in (['typed','file-backed-text'] if rep%2==0 else ['file-backed-text','typed']):
        label=f'{mode}-{rep+1}';root=OUT/label
        subprocess.run(['cp','-a','--reflink=always',str(FIX/'base'),str(root)],check=True)
        source=f'(.db.append_today (.db.splayed.get "{FIX}/tail" "{root}/.sym") 2026.10.29)'
        for file in root.rglob('*'):
            if file.is_file():
                with file.open('rb') as f:
                    while f.read(4*1024*1024):pass
        launch=OUT/f'{label}.rfl';launch.write_text(f'(set held (.db.parted.get "{root}" \'quotes_1m))\n')
        port=q.free_port();secret=secrets.token_urlsafe(24);log=(OUT/f'{label}.log').open('wb')
        p=subprocess.Popen([str(BINARY),'-c','16','-f',str(launch),'--port',f'127.0.0.1:{port}','-U',secret,'--append-root',str(root),'--append-date','2026.10.29'],stdin=subprocess.DEVNULL,stdout=log,stderr=log)
        c=None
        try:
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                assert p.poll() is None,'server launch failed'
                try:c=q.Client(port,secret);break
                except ConnectionError:time.sleep(.01)
            assert c is not None
            assert c.evaluate('(count quotes_1m)')==before
            assert c.evaluate('(set forbidden 1)')=={'error':'access'}
            Path(f'/proc/{p.pid}/clear_refs').write_text('5')
            load=os.getloadavg();t=time.monotonic_ns()
            if mode=='typed':
                c.sock.sendall(q.HEADER.pack(q.PREFIX,3,0,0,1,len(packet))+packet)
                header=q.HEADER.unpack(c.exact(16));answer=q.decode(c.exact(header[-1]))
            else:answer=c.evaluate(source)
            ack=time.monotonic_ns();assert answer==after,answer
            assert c.evaluate('(count quotes_1m)')==after
            end=time.monotonic_ns();peak=rss(p.pid)
            assert c.evaluate('(count held)')==before
            assert c.evaluate('(set still_forbidden 1)')=={'error':'access'}
            result=c.evaluate('(select {'+' '.join(f'{n}: {n}' for n in names)+' from: quotes_1m where: (and (>= ts_recv 2026.10.29D19:50:00.000000000) (< ts_recv 2026.10.29D19:51:00.000000000))})')
            assert result=={'table':columns},'all nine tail fields must match'
            row=dict(mode=mode,repeat=rep+1,append_wall_ms=(ack-t)/1e6,next_query_ms=(end-ack)/1e6,append_through_next_query_ms=(end-t)/1e6,server_peak_rss_kib=peak,load_before=load,load_after=os.getloadavg(),all_fields_equal=True)
            samples.append(row)
            (OUT/'results.json').write_text(json.dumps(dict(binary=str(BINARY),sha256=hashlib.sha256(BINARY.read_bytes()).hexdigest(),workers=16,affinity=sorted(os.sched_getaffinity(0)),cache='actual destination files read immediately before server start; warm',load='mixed; exclusive cooperating reservation',rows_before=before,rows_after=after,minute_rows=len(columns['instrument_id']),typed_request_bytes=len(packet),text_source_bytes=len(source.encode()),samples=samples),indent=2)+'\n')
            print(json.dumps(row),flush=True)
        finally:
            if c:c.close()
            p.terminate();p.wait(timeout=20);log.close()
        assert 'error:' not in (OUT/f'{label}.log').read_text()
print('ALL SIX APPENDS VERIFIED',flush=True)
