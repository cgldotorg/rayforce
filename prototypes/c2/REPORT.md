# C2: append on the product schema

The bounded correctness tests pass. These are measurements of the stated configuration, not hardware floors or a design selection. The six-section [contract](CONTRACT.md) is implemented by `series/09-product-schema-append` in `/home/gunazzi/lead-linux/rayforce-c2`, based on P3 `ef4d1923`; runtime implementation `3a96cc0a`. The original contract preceded implementation at `b907fcd9`; `03bf4de5` recorded the retention/error decisions before the inherited draft was completed. The final contract removes the proposal's obsolete pruning option. Source tests and scripts are under that worktree's `prototypes/c2/`.

The full initial contract lived in the fork worktree; the artifact-root `c2/CONTRACT.md` initially contained a pointer. Its full contents were copied there after implementation. The pre-code contract itself is preserved in Git, but this did **not** meet the literal requested artifact-path-first ordering. That chronology cannot be repaired retroactively.

## Refutations before confirmations

- The brief lists nine columns while saying eight. This test uses all nine, including STR raw_symbol and root-domain SYM parent.
- “Every failure, including disk full, never publishes” is false after manifest rename. Injected post-rename errors return `commit`; old and new generations both reopen whole. Reconciliation is required before retry; no idempotency token is provided.
- A bound parted object does not become current automatically. Held readers remain snapshots; C8 remounts its bound source before success.
- Retaining an old mmap does not establish that its filename remains reopenable. C2 retains all append generations; generic replacement keeps its old pruning policy. Unbounded retention is a prototype limitation.
- Numeric reflinks alone do not make nine-column append proportional only to the minute. STR and SYM are reconstructed for the full column. No compressed or linked append is claimed.

## Contract-to-test argument

| Contract line | Counterexample that would break it | Executed detection / result |
|---|---|---|
| A1, immutable complete generations | Writer changes the mapped file or publishes only some columns | `checks-3/results.json`: independent held process, all-field reopen and SIGKILL at all 17 checkpoints; pass |
| A2, serialized writers and old paths | Lost tail, wrong symbol or old generation pruned | Same-table dual writers, explicit old-generation reopen, all nine fields; pass |
| D1, ordered publication | `.current` selects columns or symbols not fully available | Observed SIGSTOP then SIGKILL after chain, sym, each column, schema, generation, parent, manifest, publish and directory; both explicit old path and active path compared; pass for process interruption |
| D2, commit boundary | Post-rename failure is reported as rollback | Error injection at every checkpoint asserts `io` before publish and `commit` after; pass |
| S1, shared domain serialization | Two tables assign one id to distinct new symbols | Different-table concurrent writers with a shared `.sym`, independently reopened values; pass |
| S2, symbol widths / string offsets | W8/W16 truncation or a wrapped STR pool offset | 255→257 and 65,535→65,537 domain tests compare every symbol; sparse UINT32_MAX-byte pool rejects with `range` and unchanged active fields; pass |
| I1, no stale indexes, old index retained | A trailer excludes appended rows or old index disappears | All nine new `.idx.has?` checks false; `index-control.log` requires old index true; `asof-control.log` compares all nine query fields; `sorted-check-3.log` tests a sorted prefix plus out-of-order tail, its cleared marker and ordered answer; pass |
| F1, preflight and no precommit publish | Late mismatch or clone failure exposes a partial table | Late name/type, linked tail, compressed source, string overflow and clone-0..8 errors assert error codes and old data; pass |
| F2, no false rollback promise | Retry duplicates data after uncertain publication | Post-publish injected failures require `commit` and complete new rows; pass; caller deduplication remains unbuilt |
| C1, actual equal work | A fast error/no-op or unlike output is timed | Nine successful outputs verified field by field and null mask, all three modes answer the same as-of query; pass/measured |
| C2, gates before numbers | Candidate timings precede correctness gates | Full optimized and TSan logs below completed before `benchmark-2`; pass |

`checks-3` contains 53 passing named cases; `sorted-check-3` adds the explicit sorted-marker counterexample. Its first two fixture attempts correctly failed their controls (implicit sort did not set the marker; a numeric-only seed did not create the required shared symfile); the final fixture explicitly marks sorted data and includes SYM. Test code is `prototypes/c2/checks.py`; the embedded fork test is `test/rfl/store/product_schema_append.rfl`. Timestamp nulls, real price/size nulls, empty and long STRs, and new/existing symbols are exercised. It is not an exhaustive string/null-representation proof.

The as-of positive control changes from 27,315 rows / bid-size sum 5,721,789 before the minute to 27,321 / 3,504,112 afterward. Appended, unindexed rewritten and indexed rewritten outputs match all nine query fields. Tied instrument timestamps mean this join can return more than one row per instrument. This is an untimed functional check, not a count-only performance inference.

## Exact publish order and source

1. Sync the new generation's ancestor chain under the table lock: `src/store/splay.c:1855` (`chain`).
2. Intern under the shared-domain lock, flush using `ray_sym_domain_flush_locked`, and sync even an unchanged symfile and its parent: `splay.c:1868`, `src/table/domain.c:2865` (`sym`).
3. Reflink numeric/timestamp columns or reconstruct STR/SYM, fix lengths/null/sorted/index metadata, fsync each: `splay.c:1921` (`column-0..8`).
4. Clone/fsync `.d`: `splay.c:1961` (`schema`); sync stage and parent: `splay.c:999` (`generation`, `parent`).
5. Write/fsync manifest, atomically rename to `.current`: `splay.c:289` (`manifest`, `publish`). The rename selects g+1 for fresh readers.
6. Sync table directory: `splay.c:316` (`directory`); no append pruning: `splay.c:1011`.

Before rename the active root stays g. After rename it selects whole g+1. Old explicit generation paths remain g throughout this append protocol. Temporary unpublished stages can remain after a kill. The process-kill loop does not turn this ordering argument into a hardware power-loss proof.

## Gates

- Optimized `make check`: **6,575 passed, 15 skipped, zero failed**, `full-check-2.log`, runner output `rayforce-c2/build/check/20261101T151749-3101758/summary.json`; 16 test processes, 2 runtime workers each. These correctness runs used the build lane and uncontrolled cache/load, not the reserved performance conditions.
- Linux TSan: product append 2/2; pool 116 passed/6 skipped; heap 148/11; parallel 58; stress 39; parted concurrent mounts 2. Zero failures and warnings in `tsan-2/results.json`, four configured workers. Exact observed affinity is per-filter in that JSON; the build-lane controller expanded it during execution. Suppressions are the fork's existing `.tsan-suppressions`.
- The first full optimized run had one aggregation setup failure, `agg_contract/radix_topn_waves`; isolated rerun passed, then the entire suite passed. Earlier fixture/equivalence and TSan scratch-path setup failures are retained in logs; no failed attempt supplied timing data.
- Binary hashes, including optimized and TSan variants, are in `BUILD-MANIFEST.json`.

## Measured cost

All cells are medians (minimum–maximum), **n=3 per path**, ABC/CBA/ABC inside `Northline-Terminal/scripts/serial.sh --class exclusive`. Linux btrfs, native release, **16 workers**, affinity **24-31,56-63**, **mixed background load**, load1 **4.896–6.223**. The actual destination reflink files and tail were read immediately before each operation; warm input file pages, device-cache state not independently measured. Release SHA-256 **`9b541c24ffd3bd85f10a481599edfcadd433f5f696edeaa50e0293425a6e7da0`** applies to every cell. Raw records: `benchmark-2/results.json`; harness: `prototypes/c2/benchmark.py`.

| Operation / final index state | Engine ms | Process wall s | Process peak RSS KiB | Warm as-of engine ms |
|---|---:|---:|---:|---:|
| Append / none | 560.150 (537.875–608.655) | 0.567 (0.545–0.616) | 252,844 (252,328–253,604) | 109.705 (108.805–110.812) |
| Rewrite / none | 1,391.945 (1,286.201–1,513.496) | 1.459 (1.349–1.622) | 1,690,752 (1,525,632–1,694,728) | 112.438 (110.872–116.827) |
| Rewrite / indexed | 1,819.344 (1,599.984–1,864.169) | 1.905 (1.675–1.956) | 1,950,036 (1,708,736–1,952,764) | 108.649 (107.558–110.589) |


The real 2026-10-29 19:50–19:51 UTC minute has **26,098** rows, removed from the complete 24-file source before seeding the base: **11,033,803 + 26,098 = 11,059,901**, no duplicated minute. All nine types match the contract. Raw-symbol lookup uses the source DBN metadata's date-valid instrument mapping, with no unresolved symbols; `fixture/metadata.json` records sources and sums. The prior benchmark-1 is superseded because source/device warmth did not explicitly establish warmth of each new reflink inode.

Engine time surrounds the append or concat-plus-save, including durability work. Process wall also includes startup and mounts; peak RSS is the writer process maximum, excluding the separate verification and query processes. The query is warmed once, then timed as a maximum-per-instrument plus join at 19:50 UTC. Indexed rewrite builds persisted indexes during save; append and the other rewrite are index-free. No automatic session-close rebuild was measured or built.

Checklist evidence: all operations succeeded; persisted fields and nulls match; the changed as-of control proves useful work; medians/ranges expose variation. In a separate unreported-timing profile (`profile-1/perf-report.txt`), 324 samples place 45.77% of sampled cycles in `ray_col_stream_append`; `/usr/bin/time -v` shows 0.06 s user and 0.35 s system CPU and 644,584 filesystem-output blocks. That is approximately 330 MB of accounted writes, consistent with reconstructing text/symbol columns rather than copying seven full numeric columns. The append is partly serial storage/reconstruction work; this profile does not isolate device latency from filesystem CPU or prove a maximum attainable speed. Three runs meet the brief, but are below the checklist's five for a performance verdict. No winner is selected.

## What this run could not measure

Physical power loss, torn writes, real full-device behavior, OOM, arbitrary short writes or every instruction's crash state; exhaustive cross-process schedules or hostile same-user path mutation; >UINT32_MAX symbol positions; every possible malformed/string-null encoding; cold-device speed, steady 390-append storage growth, cleanup/reclamation, multi-client tail latency, automatic index rebuild, duplicate suppression/retry reconciliation, or Terminal UI latency. TSan cannot see independent-process races. First creation and generic rewrite pruning are outside the old-generation retention promise. The installed binary and product pin were not changed.
