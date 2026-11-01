#!/usr/bin/env python3
"""Three alternating, same-schema durable operations; verification is untimed."""
import hashlib, importlib.util, json, os, re, statistics, subprocess, sys, time
from pathlib import Path
BINARY=Path(sys.argv[1]).resolve(); OUT=Path(sys.argv[2]).resolve(); OUT.mkdir(parents=True,exist_ok=False)
FIX=Path('/home/gunazzi/lead-linux/rayforce-prototypes/c2/fixture')
NAMES='instrument_id ts_recv ts_event bid_px ask_px bid_sz ask_sz raw_symbol parent'.split()
meta=json.loads((FIX/'metadata.json').read_text());samples=[];workers=16
spec=importlib.util.spec_from_file_location('q','/home/gunazzi/Northline-Terminal/.scratch/agent-r0-31/proto/rayforce/scripts/run_queries.py');q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
def run(text,label,timed=False):
    path=OUT/f'{label}.rfl';path.write_text(text+'\n')
    cmd=[str(BINARY),'-c',str(workers),'-f',str(path)]
    if timed:cmd=['/usr/bin/time','-f','%M','-o',str(OUT/f'{label}.rss'),*cmd]
    start=time.monotonic();p=subprocess.run(cmd,capture_output=True,text=True,timeout=180);wall=time.monotonic()-start
    (OUT/f'{label}.log').write_text(p.stdout+p.stderr)
    assert p.returncode==0 and 'error:' not in p.stdout+p.stderr,(label,p.stdout,p.stderr)
    return p.stdout,wall
def timer(out,prefix):
    line=next(x for x in out.splitlines() if x.startswith(prefix+' '))
    return int(re.search(r'time-ns:(\d+)',line)[1])/1e6
def save():
    (OUT/'results.json').write_text(json.dumps(dict(binary=str(BINARY),sha256=hashlib.sha256(BINARY.read_bytes()).hexdigest(),workers=workers,affinity=sorted(os.sched_getaffinity(0)),cache='warm',load='mixed background load; exclusive cooperating reservation',fixture=meta,samples=samples),indent=2)+'\n')
for rep in range(3):
    for mode in (['append','rewrite','indexed'] if rep%2==0 else ['indexed','rewrite','append']):
        label=f'{mode}-{rep+1}';root=OUT/label
        subprocess.run(['cp','-a','--reflink=always',str(FIX/'base'),str(root)],check=True)
        # Fresh reflinks have distinct page-cache mappings: warm those actual
        # files, not only the source inode or the underlying device cache.
        for file in list(root.rglob('*'))+list((FIX/'tail').rglob('*')):
            if file.is_file():
                with file.open('rb') as f:
                    while f.read(4*1024*1024): pass
        dest=root/'2026.10.29/quotes_1m';sym=root/'.sym'
        pre=f'(set old (.db.splayed.get "{dest}" "{sym}"))\n(set tail (.db.splayed.get "{FIX}/tail" "{sym}"))\n'
        if mode=='append':op=f'(.db.splayed.append "{dest}" tail "{sym}")'
        else:
            cols=' '.join(f"(.idx.drop (concat (at old '{n}) (at tail '{n})))" for n in NAMES)
            op=f'(count (.db.splayed.set "{dest}" (table [{" ".join(NAMES)}] (list {cols})) "{sym}" {{compress: false index: {"true" if mode=="indexed" else "false"}}}))'
        load_before=os.getloadavg()
        out,wall=run(pre+f'(println "OP" (.mem.ts {op}))\n(println "HELD" (count old))',label,True)
        assert f'HELD {meta["rows"]["base"]}' in out
        row=dict(path=mode,repeat=rep+1,engine_ms=timer(out,'OP'),process_s=wall,peak_rss_kib=int((OUT/f'{label}.rss').read_text()),load_before=load_before,load_after=os.getloadavg())
        # Independently reopen persisted output; force every value and null-mask comparison.
        verify=f'(set a (.db.splayed.get "{FIX}/base/2026.10.29/quotes_1m" "{FIX}/base/.sym"))\n(set tail (.db.splayed.get "{FIX}/tail" "{FIX}/base/.sym"))\n(set b (.db.splayed.get "{dest}" "{sym}"))\n'
        verify+=f'(if (!= (count b) {sum(meta["rows"].values())}) (raise "row mismatch"))\n'
        for n in NAMES:
            verify+=f"(set x (concat (at a '{n}) (at tail '{n})))\n(set y (at b '{n}))\n(if (not (all (and (== (nil? x) (nil? y)) (or (nil? x) (== x y))))) (raise \"field {n}\"))\n"
            if mode!='indexed':verify+=f"(if (.idx.has? y) (raise \"stale index {n}\"))\n"
        verify+='(println "VERIFIED_ALL_FIELDS")'
        v,_=run(verify,'verify-'+label);assert 'VERIFIED_ALL_FIELDS' in v
        query=f'(set held (.db.splayed.get "{dest}" "{sym}"))\n(set T 2026.10.29D19:50:00.000000000)\n'
        expr=f'(count {q.latest_joined("held")})'
        query+=f'(println "WARM" {expr})\n(println "QUERY" (.mem.ts {expr}))\n'
        result,_=run(query,'query-'+label)
        row['asof_ms']=timer(result,'QUERY');row['asof_rows']=int(re.search(r'^WARM (\d+)',result,re.M)[1]);row['all_fields_equal']=True
        samples.append(row);save();print(json.dumps(row),flush=True)
assert len({s['asof_rows'] for s in samples})==1
print('ALL NINE OUTPUTS VERIFIED',flush=True)
