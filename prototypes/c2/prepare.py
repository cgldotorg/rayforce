#!/usr/bin/env python3
"""Enrich the existing full-session CSV with DBN metadata raw symbols.

Fixture preparation only, outside every timed region. Never writes Library.
"""
import datetime
import json
from pathlib import Path
import databento as db
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv

OUT=Path('/home/gunazzi/lead-linux/rayforce-prototypes/c2/fixture')
OUT.mkdir(parents=True,exist_ok=False)
LIB=Path('/home/gunazzi/eyes/options.omon-chain@a1153ba9-20261031T110530Z/home/.local/share/northlineterminal/library/GLBX.MDP3/bbo-1m')
SOURCE=Path('/home/gunazzi/lead-linux/rayforce-prototypes/r4/full-session.csv')
DAY=datetime.date(2026,10,29)
mapping={}; files=[]
for file in sorted(LIB.glob('*/2026-10-29*.dbn.zst')):
    files.append(str(file))
    metadata=db.DBNStore.from_file(file).metadata
    for raw,intervals in metadata.mappings.items():
        for interval in intervals:
            if interval['start_date']<=DAY<interval['end_date']:
                instrument=int(interval['symbol'])
                assert instrument not in mapping or mapping[instrument]==raw
                mapping[instrument]=raw
ids=pa.array(sorted(mapping),type=pa.int64())
strings=pa.array([mapping[i] for i in sorted(mapping)])
names='instrument_id ts_recv ts_event bid_px ask_px bid_sz ask_sz raw_symbol parent'.split()
minute=1793303400000000000  # the real P2 minute, 2026-10-29 19:50 UTC
reader=csv.open_csv(SOURCE,read_options=csv.ReadOptions(block_size=64*1024*1024),convert_options=csv.ConvertOptions(column_types={n:pa.int64() for n in names if n not in ('parent','raw_symbol')}))
writers={}; counts={'base':0,'tail':0}; sums={'base':0,'tail':0}
try:
    for batch in reader:
        table=pa.Table.from_batches([batch])
        positions=pc.index_in(table['instrument_id'],value_set=ids)
        assert positions.null_count==0,'unresolved raw symbol'
        table=table.append_column('raw_symbol',pc.take(strings,positions)).select(names)
        is_minute=pc.and_(pc.greater_equal(table['ts_recv'],minute),pc.less(table['ts_recv'],minute+60_000_000_000))
        for label,mask in [('base',pc.invert(is_minute)),('tail',is_minute)]:
            t=table.filter(mask)
            if label not in writers:
                writers[label]=csv.CSVWriter(OUT/f'{label}.csv',t.schema)
            writers[label].write_table(t)
            counts[label]+=t.num_rows
            sums[label]+=pc.sum(t['instrument_id']).as_py() or 0
finally:
    for w in writers.values(): w.close()
assert sum(counts.values())==11_059_901,counts
(OUT/'metadata.json').write_text(json.dumps(dict(source=str(SOURCE),dbn_files=files,rows=counts,instrument_sum=sums,tail_start_ns=minute,tail_stop_ns=minute+60_000_000_000,raw_symbol_mapping='DBN metadata valid on 2026-10-29; no missing mappings',columns=names),indent=2)+'\n')
print(json.dumps(counts))
