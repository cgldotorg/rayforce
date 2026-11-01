# P1 — durable streaming with a shared symbol file

## Resume using optimized local checks

The original P1 changes are checkpointed in local commit `54361a93`; the
machine-optimized build/check workflow was cherry-picked as `60acf8aa`. The
P1 worktree's optimized focused CSV/RFL check passed 81 cases with one
environment-dependent skip, including both shared-symbol layouts and a new
POSIX debug process-crash test. The test stops a child immediately after the
durable shared symbol file flush, kills it, verifies every old symbol remains
readable, then retries the write and verifies the replacement values. Existing
cancel tests also check the original symbols, not just the row count. This
does not simulate a machine reboot or power loss.

The final optimized native sanitizer check on `c9df046d` selected 6,587
cases and passed 6,572 with 15 environment-dependent skips; see
`build/check/20261101T142804-2563046/summary.json`. The native release was
built on that commit (SHA-256
`634ef5988b49fa13698f94c9667c1afcb7bf026aa5811afe877420f0f6a61c1b`).
The updated native release on `c9df046d` was measured with 16 explicitly
requested Rayforce workers under the Northline exclusive reservation. Three
alternating warm-cache runs on the same 8,344,972-row CSV gave a durable
streaming median of **0.874 s / 796,688 KiB peak RSS**, and a
materialize-then-durable-save median of **1.483 s / 1,656,828 KiB peak RSS**.
Each timed child reopens the parted table and verifies row count, instrument
sum and distinct parent count. System load1 during the run was 16–17, so this
is a mixed-load local comparison rather than a quiet-box result. The paths,
SHA-256, CPU affinity, explicit worker count, per-run load, and individual
results are in `/home/gunazzi/lead-linux/rayforce-prototypes/p1-native-16/`.
The 16-worker run uses a 16-CPU affinity reservation and must not be pooled
directly with the following whole-machine runs, which had a 64-CPU mask.

Under one whole-machine quiet-box reservation, using the same input and
binary, each worker configuration ran three alternating warm-cache trials:

| Workers | Stream median / peak RSS | Materialize median / peak RSS |
|---|---|---|
| 32 | 0.925 s / 796,840 KiB | 1.392 s / 1,657,464 KiB |
| 64 | 1.111 s / 799,224 KiB | 2.134 s / 1,514,680 KiB |

The 32-worker trials preceded the 64-worker trials rather than alternating
worker configurations; both paths alternate within each configuration. The
host's desktop and other non-cooperating activity remained present, load1 was
roughly 7.0–7.4, and the filesystem cache was warm. These measurements do not
establish the best worker count in other workloads. Metadata and all samples
are under `/home/gunazzi/lead-linux/rayforce-prototypes/p1-native-32/` and
`/home/gunazzi/lead-linux/rayforce-prototypes/p1-native-64/`.

`verify-source.py` independently exported the reopened streaming partition and
used Python's CSV parser to compare it against the original CSV, field by
field and row by row. All eight fields and nulls matched across all 8,344,972
rows (`p1-native-32/source-verification.log`). This was an untimed validation,
not part of any benchmark.

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
