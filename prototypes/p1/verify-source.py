#!/usr/bin/env python3
"""Compare every persisted cell to the original CSV using Python's CSV reader."""
import csv
from itertools import zip_longest
from pathlib import Path
import subprocess
import sys
import tempfile

binary, source, db, workspace = (Path(p).resolve() for p in sys.argv[1:5])
script = Path(__file__).with_name("export.rfl").resolve()
workspace.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="verify-csv-", dir=workspace) as d:
    exported = Path(d) / "export.csv"
    result = subprocess.run([str(binary), "-f", str(script), "--", "-db", str(db),
                             "-out", str(exported)], capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise RuntimeError(f"export failed: {result.stdout}\n{result.stderr}")
    with source.open(newline="") as a, exported.open(newline="") as b:
        original, stored = csv.reader(a), csv.reader(b)
        rows = 0
        for number, (left, right) in enumerate(zip_longest(original, stored), 1):
            if left != right:
                raise AssertionError(f"CSV mismatch at line {number}: {left!r} != {right!r}")
            rows += 1
    print(f"PASS independent CSV equality: {rows - 1} rows, all eight fields and nulls", flush=True)
