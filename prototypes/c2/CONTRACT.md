# C2: product-schema append contract

The pre-implementation proposal is preserved at fork commit `b907fcd9` in
`prototypes/c2/CONTRACT.md`; pre-completion decisions at `03bf4de5`. This final
copy resolves the proposal's retention question and records falsifiable scope.
The brief enumerates **nine**, not eight, columns: instrument_id I64, ts_recv
TIMESTAMP, ts_event TIMESTAMP, bid_px/ask_px/bid_sz/ask_sz I64, raw_symbol STR,
parent SYM. The supported destination is an existing uncompressed generation-0
table on Linux with FICLONE; trusted paths and cooperative writers are assumed.
The general builtin requires exactly `(path, table, root_sym_path)` and remains
restricted. C8 is the separate launch-bound authorization layer.

## 1. Atomicity and visibility

A1. Append serializes same-table writers and publishes one immutable generation.
A resolving read gets either the complete old or complete new table, never a
mixture. An already-mapped table/parted object remains unchanged, including
its symbols, strings and indexes. A fresh `.db.parted.get` resolves `.current`
and refreshes changed entries in its path-keyed per-thread cache. C2 does not
refresh a variable holding the old object; the caller remounts. C8 refreshes
`quotes_1m` before acknowledging success.

A2. A successful append returns old_rows + tail_rows; simultaneous cooperating
appends lose no rows. Old explicit `.generations/<id>` paths remain reopenable
through subsequent appends. No automatic pruning occurs on this path. This
retention promise does not cover a later generic rewrite, or an original
legacy root path whose meaning changes when `.current` is first installed.

Counterexample/tests: publishing columns individually, overwriting old files,
or losing one writer's tail fails `checks.py`'s every-field reopen, 17 stopped
writer checks, held-reader/two-writer comparison and old-generation reopen.
C8 tests the fresh parted binding and unchanged held binding on one connection;
R1 supplies independent existing-server observations.

## 2. Durability and publication

D1. Successful append uses this order (the directory helper syncs its argument's
**parent**, not the argument itself):

1. Under the table lock, create the hidden generation and sync its ancestor
   directory chain. Checkpoint `chain`.
2. Under `<root_sym_path>.lk`, refresh and extend the append-only symbol domain;
   sync its replacement file, rename and sync its parent. Explicitly sync the
   resulting symfile and parent even if no symbol was added. Checkpoint `sym`.
3. Reflink each numeric/timestamp column, append and repair its header; stream
   complete STR/SYM columns into fresh files. Sync each completed file before
   checkpoints `column-0` through `column-8`.
4. Clone and fsync `.d` (`schema`); sync the completed generation directory
   (`generation`) and its `.generations` parent (`parent`).
5. Write and fsync the temporary manifest (`manifest`). Atomically rename it
   to `.current` (`publish`): this is the visibility point.
6. Fsync the table directory (`directory`). Return success only afterward.
   Retain old generations; there is no append pruning step.

D2. After each completed step, a process crash leaves old generation g readable
and g+1 either unpublished or whole. Before step 5's rename a new resolving
reader gets g; afterward it gets g+1. A stage may remain on disk without being
published. A failure after rename returns `commit`, meaning publication
occurred and the caller must reconcile before retrying. `io` before rename
means this attempt did not replace `.current`.

Counterexample/tests: a publication referencing missing symbols/files, a torn
logical table or old-generation deletion fails the SIGSTOP-observed/SIGKILL
loop at all 17 checkpoints and the corresponding error loop in `checks.py`.
These tests cover process termination after grouped completed operations.
The intended persistence order is not proof of physical power-loss behavior,
torn device writes, or crashes at every instruction inside a grouped step.

## 3. Symbols and strings

S1. New parent values receive permanent root-domain positions while the shared
lock is held, and are durable before column publication. Failure may leave
unused symbols; existing positions do not change. Two different tables sharing
one symfile must both preserve their distinct new symbols.

S2. SYM output uses W32; old W8/W16 codes are translated cell by cell. Crossing
255 and 65,535 domain entries must preserve every symbol. STR output preserves
bytes, empty strings and supported null representation, rebases pool offsets,
and rejects a combined pool beyond UINT32_MAX with `range` before publication.

Counterexample/tests: colliding domain positions fail the different-table
concurrent-writer test; truncated codes fail both boundary tests; mis-rebased
strings fail every-field comparison; offset wrap fails the sparse 4 GiB pool
rejection test. Timestamp nulls and empty/long strings are in the small fixture;
real-minute null masks and fields are independently reopened. More than
UINT32_MAX domain positions, arbitrary malformed files and every possible
string/null encoding are not exercised by this suite.

## 4. Saved indexes

I1. Append drops all persisted index trailers and sorted flags in the new
generation. The old mapped generation keeps its indexes. The appended partition
stays index-free until a separate explicit rebuild/rewrite; no session-close
scheduler is provided. A query must still give the same answer on appended,
unindexed rewritten and indexed rewritten copies of identical values.

Counterexample/tests: a stale index surviving append fails nine `.idx.has?`
assertions; stale lookup results fail the as-of comparison. The benchmark
compares all nine persisted columns and null masks before measuring the same
maximum-per-instrument plus join question on all three outputs. It records
latency for each index state; no claim that indexes necessarily accelerate
that question follows from it.

## 5. Failure behavior

F1. Late column-name/order or type mismatch returns `type`; linked or encoded
storage returns `domain`; STR pool overflow returns `range`. Each leaves
`.current` unchanged and old fields readable. Whole-table preflight precedes
symbol interning and column cloning. Unsupported clones and prepublication
write/fsync errors return `io` without publication.

F2. Errors after manifest rename return `commit`, including failure of the
final directory sync. Thus the brief's unconditional “disk full never publishes”
cannot be promised: an error after visibility is not rollback.

Counterexample/tests: late-name/type, linked-tail, compressed-source and sparse
pool cases assert the error and unchanged reopened data. `clone-0..8` failure
injection verifies mid-operation abort, and all publication checkpoints verify
old/new field equality and `io` versus `commit`. Synthetic ENOSPC checkpoints
exercise error propagation; they do not fill a real device, simulate every
short write, force OOM, or establish arbitrary-path safety for privileged callers.

## 6. Cost and validation

C1. Report three alternating release runs of one disjoint real minute into an
approximately 11M-row indexed base, beside unindexed and indexed rewrites of
the same nine columns. Each sample must succeed, reopen field-equal, and use
`serial.sh --class exclusive`, reserved CPUs 24-31,56-63, recorded worker count,
load, cache preparation and binary SHA-256. Report engine time, process peak
RSS and the subsequent as-of query, with medians and ranges.

C2. Before reporting performance, complete optimized `make check` and Linux
TSan product/store, pool, heap, parallel and stress filters. A failed operation
is never a timing sample. A separate profiler run informs the limiter discussion.

Counterexample/tests: benchmark assertions reject errors, missing work, field
mismatch and stale indexes; JSON records expose sample counts/conditions and
permit median recomputation. Full check/TSan logs provide the gate. TSan does
not detect independent-process races. Neither three samples nor profiler
samples establish a hardware minimum, cold-storage performance, whole-day
retained-generation growth, or Terminal UI latency.
