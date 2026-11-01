# C2 append contract — proposal, 2026-11-01

Status: **proposed, not yet implemented or validated**. This document precedes
the C implementation. Success means the tests and measurements below have run
against the exact candidate; no guarantee here is claimed for P3 as it stands.
The request says eight columns but enumerates nine: instrument_id, ts_recv,
ts_event, bid_px, ask_px, bid_sz, ask_sz, raw_symbol, parent. This contract
uses those nine, in that order, with I64, TIMESTAMP, TIMESTAMP, I64, I64,
I64, I64, STR, SYM types. Root `.sym` is shared by all partitions.

Implementation decisions fixed before completing the inherited C draft:
numeric/timestamp columns use reflinks; STR and SYM are streamed into new files,
with bounded buffers and no full materialized concatenation. SYM output is W32
at every append, so width transitions are handled by translating every old and
new cell; domain counts beyond UINT32_MAX are rejected. STR pool offsets are
rebased by the existing bounded column-stream writer, which rejects overflow.
All schema/storage checks precede symbol interning. All old generation paths
are retained by append (ordinary rewrite retains its existing pruning policy).
An error after manifest rename answers the distinct eight-byte-safe code
`commit`: publication happened, acknowledgement durability is uncertain.
Tests stop after ancestry, symfile, each individual column, schema, stage
directory, generation parent, manifest sync, manifest rename and directory sync.
The same checkpoints inject I/O failures. C8 performs the explicit remount
before acknowledgement; C2 itself preserves immutable snapshot semantics.

## 1. Atomicity and visibility

Append writes a new immutable physical generation while holding the target
splayed table's writer lock. No reader receives a partial generation. An
already mapped reader remains on its previous snapshot; R1 establishes this
also for a parted object held by a running server. A fresh mount resolves
`.current` and sees the complete generation selected there. The caller must
remount `.db.parted.get` for its next query or call a nullary mount function;
invalidating the path-keyed per-thread cache alone does not refresh an
already-held parted object. Appending does not mutate a caller-held value.
Cross-process held-reader and remount tests must exercise all nine columns,
including new symbols, strings and nulls. Two concurrent table writers must
both succeed or return a documented error without loss or partial publish.

## 2. Durability and publication

Intended ordering (exact code lines and failure-injection evidence must be
added when implemented):

1. Create the generation directory under the held table lock; sync any new
   directory entries needed to reach it.
2. Resolve and append new root-domain symbols while holding the shared-domain
   writer lock; durably flush the shared symfile and its parent before any
   generation referencing the new positions can become current.
3. Write/reflink the new generation's column files, including the string pool
   and symbol codes, strip stale indexes, and fsync every completed file.
4. Write the generation's `.d` schema; fsync it and then sync the generation
   and its parent directory entries.
5. Write and fsync the temporary `.current` manifest, rename it atomically
   onto `.current` (the visibility point), then fsync the table root.
6. Retire/prune only generations whose removal does not invalidate any
   promised reopen or already-mapped reader; sync required directory changes.

Before step 5 rename, the old generation remains current and reopenable.
After the rename, a fresh reader may see the new complete generation. A
failure after rename but before the root fsync is **ambiguous**: the caller
must inspect the current generation and must not blindly retry. A successful
return requires all durability steps. SIGKILL after each exposed step tests
process interruption, not loss of kernel cache or storage power; no physical
power-loss guarantee is proven without a fault-capable filesystem test.
P3 currently prunes older generations after a successful publish, so it does
not establish a blanket claim that generation g remains reopenable by path
at every later step. Decide and test retention before making such a claim.

## 3. Symbols and strings

Translate every appended `parent` value into the root sym domain while the
domain lock excludes competing writers; append positions are permanent and
flush precedes publication. A failure may leave extra unused symbols but must
not leave a published column pointing to missing or remapped positions. Cover
new symbols introduced concurrently by independent processes. Width changes
at 255 and 65,535 positions must be supported safely (widen old codes when
needed, or select W32/W64 for the new complete column); no overflow or silent
truncation. `raw_symbol` retains every string byte and empty/null semantics;
the output string pool and its 32-bit offsets must be checked for overflow and
either produced intact or rejected before publication. Verify strings, domain
values and nulls field by field after reopen, including width crossings.

## 4. Saved indexes

The first candidate discards stale persisted index trailers on the new
generation and leaves it index-free until an explicit separate rebuild. It
does not claim automatic close-of-session rebuild. Existing mapped readers
retain their old index as part of their prior snapshot. Tests inspect persisted
metadata after reopen and check that an as-of query gives the correct answer.
Measure as-of query latency for index-free appended and indexed/rebuilt or
rewritten generations on equivalent data, with their index state stated.

## 5. Failure behavior

Validate schema names, order, rectangularity, types, counts and safe paths;
reject unsupported compressed or linked columns, schema mismatch, string-pool
overflow and unsupported clone operations with a typed error before manifest
rename. Failed clone/write/fsync or disk-full before rename must not publish;
an old fresh mount remains readable. Failure of the final root fsync after
rename is an indeterminate publication, not a no-publish guarantee. Injection
must verify both paths and make post-rename ambiguity visible. Nothing here
extends `-U` IPC access; this builtin remains restricted.

## 6. Cost and validation

Measure one approximately 22,000-row real minute on an 11M-row nine-column
partition, native release, against a like-for-like rewrite with both index
states reported. Alternate at least three runs inside `serial.sh --class
exclusive`, record worker count, affinity, load, page-cache condition, binary
hash, engine wall and peak RSS. Compare all fields after reopen. Measure
as-of queries beside the append and rewrite. Run optimized `make check`, Linux
TSan filters, held-reader, dual-writer, schema/type/null, string-pool,
symbol-width, index, error and SIGKILL-after-each-step tests. Report exactly
which passed and what remains unmeasured; a test gap is not a contract met.
