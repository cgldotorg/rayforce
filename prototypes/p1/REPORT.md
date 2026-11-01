# P1 — durable streaming with a shared symbol file

This is an isolated experiment based on `8dd08ef8`, not a product binary. The
prototype adds `.csv.splayed` options `sym_path` and `durable`; the existing
default remains a local `.sym` and a non-durable bulk write. When `durable` is
true the experiment syncs the directory chain, symfile, column files and
renames, `.d` schema, and staged generation publication. A durable run also
syncs an existing symfile even when no new symbols were added.

## Measurements

Three alternating runs imported the same cached 627,962,244-byte CSV of
8,344,972 real quote records. Both paths used the **same modified candidate**:
one called `.csv.read` plus `.db.splayed.set` using the root `.sym`, and the
other called durable `.csv.splayed` with that root `.sym`. Each run used a new
pre-created root, launched a fresh child, wrote into its date partition, and
reopened the table through `.db.parted.get`; wall time includes startup,
import, reopen and the row-count/sum/distinct checks. The times exclude CSV
production and timestamp recasting; both paths store the timestamps as raw
I64. The original product's TIMESTAMP conversion and CSV preparation are not
included and must be included when assessing end-to-end performance.

| Path | Process wall seconds, three runs | Median | Median peak RSS |
|---|---|---:|---:|
| Materialize, durable save | 1.628, 1.690, 1.669 | 1.669 s | 1,526,468 KiB |
| Durable streaming | 1.192, 1.192, 1.250 | 1.192 s | 719,900 KiB |

The machine-wide exclusive *measurement* reservation pinned the process to
CPUs `24-31,56-63` and serialized other cooperating measurements; it did not
stop desktop activity or builds. System load1 was 3.34–3.39, and pages were
warm. The figures are an exploratory same-machine comparison, not a cold
start, production SLA, or a comparison against the shipped 2.10 binary.

`compare.rfl` reopens the independently written baseline and stream roots,
checks equal schema and all values and null masks in all eight columns. The
two paths matched on all 8,344,972 rows, including all 5,103,471 `ts_event`
nulls. Both imports also returned the expected sum of instrument IDs and 22
distinct parents. This compares two Rayforce parsers/paths; it is not a
separate full CSV-to-store audit.
The comparator raises on mismatches; `verify-comparator.py` deliberately
changed one instrument ID and one timestamp null in disposable reflink copies
and verified that both mismatches caused failures.

Raw artifacts: `/home/gunazzi/lead-linux/rayforce-prototypes/p1-full-session-v4/`
contains `results.json`, `compare.txt`, sanitizer logs, all output roots, and
the measured release executable `rayforce-p1` (SHA-256
`f20123034f0a62efbbe4bd5af65a4ae5cf624da51b44e1b6356b8d69f92f104c`).
The scripts live alongside this report. The reservation log is
`/tmp/northline-build.log` at 2026-11-01T12:35:45Z. Earlier v3 artifacts are
preserved; v4 includes the path guard in the measured candidate.

## Tests and limits

- ASan+UBSan `TEST_FILTER=csv_splayed`: 8 passed, including two date
  partitions sharing a symfile, a replacement generation and malformed
  options.
- `TEST_FILTER=csv/splayed_cancel`: 2 passed and 1 upstream hash case skipped
  because this filesystem does not take the in-place hash path. The shared-sym
  durable case injects cancellation during append and finish and verifies the
  old generation remains readable. This is an error/cancellation check, not a
  process-kill, reboot, or power-loss durability proof.
- The explicit symfile path is refused if its canonical parent is inside the
  destination table, if the final file is a symlink or a hardlink, or if it
  names the source inode. Regression cases include the destination column and
  schema, parent symlink aliases, and hardlinks to the source, column and
  schema; they verify the source and prior partition remain intact. This
  conservative prototype does not defend against a malicious process changing
  paths between validation and use. Explicit shared paths are rejected on
  Windows until a safe equivalent exists.
- The bounded four-trial two-process race (`concurrent.py`) saw either both
  writers succeed with matching rereads, or one succeed and one fail with
  `corrupt` before publication. The seed partition survived. The writer does
  not serialize or retry shared-symbol conflicts; this is not a general
  concurrency proof. Full crash-recovery, platform and product integration
  tests remain. Do not promote the implementation as a finished feature.
