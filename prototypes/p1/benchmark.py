#!/usr/bin/env python3
"""Compare full-session splayed paths; run inside a measurement reservation."""
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

binary, source, result_dir = map(lambda p: Path(p).resolve(), sys.argv[1:4])
result_dir.mkdir(parents=True, exist_ok=False)
script = Path(__file__).with_name("import.rfl").resolve()
expected = {"ROWS": "8344972", "INSTRUMENT_SUM": "264400196857973", "PARENTS": "22"}
records = []
for i in range(3):
    for mode in (("baseline", "stream") if i % 2 == 0 else ("stream", "baseline")):
        root = result_dir / f"{mode}-{i + 1}"
        (root / "2026.10.29").mkdir(parents=True)
        timing = result_dir / f"{mode}-{i + 1}.time"
        cmd = ["/usr/bin/time", "-f", "%M %U %S", "-o", str(timing), str(binary),
               "-f", str(script), "--", "-csv", str(source), "-db", str(root), "-mode", mode]
        start = time.monotonic_ns()
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        elapsed = (time.monotonic_ns() - start) / 1e9
        if r.returncode:
            raise RuntimeError(f"{mode} exited {r.returncode}: {r.stdout}\n{r.stderr}")
        values = dict(re.findall(r"^(ROWS|INSTRUMENT_SUM|PARENTS) (\d+)$", r.stdout, re.MULTILINE))
        if values != expected:
            raise RuntimeError(f"incorrect {mode}: {values!r}, stdout={r.stdout!r}, stderr={r.stderr!r}")
        rss, user, system = timing.read_text().split()
        record = {"mode": mode, "repeat": i + 1, "wall_seconds": elapsed,
                  "peak_rss_kib": int(rss), "user_seconds": float(user), "system_seconds": float(system),
                  "values": values, "loadavg": os.getloadavg()}
        records.append(record)
        print(json.dumps(record), flush=True)
        (result_dir / "results.json").write_text(json.dumps(records, indent=2) + "\n")
for mode in ("baseline", "stream"):
    selected = [r for r in records if r["mode"] == mode]
    print(mode, "median_seconds", statistics.median(r["wall_seconds"] for r in selected),
          "median_peak_rss_kib", statistics.median(r["peak_rss_kib"] for r in selected), flush=True)
