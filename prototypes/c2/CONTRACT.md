# C2: durable append contract

Written 2026-11-01 before C2 implementation. This is the intended contract;
REPORT.md records what the implementation and evidence actually establish.
Linux, local reflink-capable filesystem, ordinary file-based shared symbol
domain. The input schema is nine columns (the brief says eight but enumerates
nine): instrument_id I64, ts_recv TIMESTAMP, ts_event TIMESTAMP, bid_px I64,
ask_px I64, bid_sz I64, ask_sz I64, raw_symbol STR, parent SYM. The generic
builtin accepts matching ordered schemas drawn from these four types.

## 1. Atomicity and visibility

`.db.splayed.append(path, table, sym_path)` serializes writers with the existing
partition `.write.lock`. It clones into an unpublished generation and never
changes published column bytes. A mapped reader keeps its complete old view;
a fresh open after the atomic `.current` rename obtains the complete new view.
Rows from two successful appends are both present, in lock acquisition order.
No partial table is published. Append requires an existing table.

A bound table is a snapshot, not a live subscription. Another process's
publish does not mutate that value. Reopening `.db.parted.get` re-resolves the
generation and replaces the path-keyed partition cache entry. C8's engine
capability performs this remount and replaces the launch-bound `quotes_1m`
binding before acknowledging success; the next request on that connection
uses it. Held values remain snapshots. R1 supplies the external-server evidence.

## 2. Durability

The append preserves old generations for recovery (including the legacy root
files); cleanup is an explicit later operation, outside this prototype. The
existing generic rewrite path may prune them, so this retention claim applies
to append-only histories. Numbered durable checkpoints, injected only by the
external test harness, are:

1. Sync the existing root's directory chain and the generation parent, making
   the private generation's ancestry durable.
2. Under `<sym>.lk`, refresh the domain, intern tail symbols, flush the symfile
   through a synced temporary file, rename it, and sync its parent directory.
   Existing symbol positions remain permanent. No column is published first.
3. Sync every completed cloned/rewritten column, in schema order (one test
   checkpoint for each column).
4. Sync the cloned `.d` schema.
5. Sync the new generation directory and `.generations` directory.
6. Write and sync the temporary manifest containing the new generation name.
7. Atomically rename the manifest to `.current`, then sync the table directory.

After each completed numbered checkpoint, a crash leaves generation g readable
and published generation g+1 either absent or whole. Private staging files may
be partial before step 5 and are never a published generation. Step 7's rename
is the visibility point; its final sync is the durable acknowledgement point.
A kill test is evidence about process death, not power loss or a dishonest
storage device. Old files remain openable for independent field comparison.

## 3. Symbols and strings

The symfile lock spans refresh, interning, and durable flush. Positions are
never reassigned. A failed append may leave unused new dictionary entries;
it cannot change the meaning of old values. W8/W16/W32 follows the engine's
domain-count rule; crossing 255 or 65,535 entries widens the cloned SYM payload
by rewriting its ids. Otherwise the existing width is kept or widened, never
truncated. Tail ids are translated from their source domain.

STR uses 16-byte descriptors followed by a pool header and byte pool. Growing
the descriptors moves the pool inside the private clone; old descriptors keep
their offsets and new descriptors rebase onto the old pool length. Long-string
hashes are valid. Pool growth past UINT32_MAX fails with `range` before publish.
Null/empty and inline/pooled strings retain the engine's existing semantics.

## 4. Indexes

Append removes every persisted index trailer and sorted flag; the resulting
generation is index-free. It does not silently claim incremental indexes or
schedule a close-time rebuild. A caller may perform an indexed durable rewrite
at session close. Measurements compare append and rewrite with indexes off,
and the as-of query on appended, unindexed-rewritten, and indexed-rewritten
data. Saved indexes in the source must not survive as stale trailers.

## 5. Failure

Schema/name/order/type mismatch answers `type`; compressed, linked or unsupported
storage answers `domain`; bounds overflow answers `range`; clone, write, sync
and ENOSPC failures before manifest rename answer `io`. None publishes a new
generation. Validation covers all columns before modifying symbols or payloads.
Unpublished files are removed on ordinary failure; kill may leave hidden stages.

The brief's unconditional “disk full never publishes” cannot be guaranteed if
an error happens after atomic rename. A final directory-sync failure has a
commit-uncertain outcome: the new complete generation may already be visible.
The caller must reopen/reconcile, never blindly retry. The report must show this
case distinctly. A successful append is not an idempotent request.

## 6. Cost and evidence obligations

Use an approximately 11 M-row full session and one actual clock minute, retaining
all nine columns. Record exact row counts and symbol provenance. Three alternating
append/rewrite runs under the exclusive serial reservation, warm cache, reserved
affinity, same worker count and release binary; report engine time, wall, peak
RSS, load1, SHA-256, and all samples. Verify fields independently, not just sums.
Include the as-of latency comparison and benchmark checklist evidence. Required
correctness cases: checkpoints and ordinary I/O failures, width boundaries,
strings/nulls/index removal, held separate-process reader, competing writers,
optimized full check and focused Linux TSan. REPORT.md must distinguish evidence
still pending from passing results and end with what the run could not measure.
