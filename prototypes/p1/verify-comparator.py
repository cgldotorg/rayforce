#!/usr/bin/env python3
"""Verify comparator rejects a changed value and a changed null mask."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

binary, baseline, workspace = (Path(p).resolve() for p in sys.argv[1:4])
compare = Path(__file__).with_name('compare.rfl').resolve()
with tempfile.TemporaryDirectory(prefix='compare-mismatch-', dir=workspace) as tmp:
    clone = Path(tmp) / 'clone'
    subprocess.run(['cp', '-a', '--reflink=always', str(baseline), str(clone)], check=True)
    column_root = clone / '2026.10.29' / 'quotes'
    def run():
        return subprocess.run([str(binary), '-f', str(compare), '--', '-baseline', str(baseline),
                               '-stream', str(clone)], text=True, capture_output=True, timeout=120)
    col = column_root / 'instrument_id'
    with col.open('r+b') as f:
        f.seek(32); original = f.read(8)
        f.seek(32); f.write(struct.pack('<q', struct.unpack('<q', original)[0] + 1))
    result = run()
    if result.returncode == 0 or 'mismatch' not in result.stderr:
        raise AssertionError(f'value mismatch was not rejected: {result.returncode}, {result.stdout}, {result.stderr}')
    print('PASS intentional instrument_id value mismatch was rejected')
    with col.open('r+b') as f:
        f.seek(32); f.write(original)
    with (column_root / 'ts_event').open('r+b') as f:
        f.seek(32); previous = struct.unpack('<q', f.read(8))[0]
        assert previous == -(2**63), previous
        f.seek(32); f.write(struct.pack('<q', 0))
    result = run()
    if result.returncode == 0 or 'mismatch' not in result.stderr:
        raise AssertionError(f'null mismatch was not rejected: {result.returncode}, {result.stdout}, {result.stderr}')
    print('PASS intentional ts_event null mismatch was rejected')
