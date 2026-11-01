# C8: launch-bound restricted append contract

Written 2026-11-01 before C8 implementation. Proposed prototype contract;
REPORT.md distinguishes tested results from remaining proof limits. The original
pre-implementation contract is committed at `76181b1e`.

## 1. Capability surface

Exactly one additional restricted-peer builtin, `.db.append_today(table, date)`.
The trusted launch supplies an absolute mounted root and fixed date using
process arguments `--append-root ROOT --append-date YYYY.MM.DD`; absent
configuration denies the builtin. The table name
and refreshed global binding are fixed as `quotes_1m`. The peer supplies no
path, root, filename, symbol path, binding name or executable. Date mismatch,
extra path arguments, missing configuration or a root escape answers `access`.
Only an existing `<root>/<date>/quotes_1m` table can be appended. No creation,
rewrite, delete or arbitrary file write. Symbol persistence uses `<root>/.sym`.
The root and partition paths are canonicalized/validated against escape links;
the trust model excludes a hostile same-user process replacing filesystem paths.

## 2. Newly permitted damage

Typed text can append arbitrary schema-valid rows to the fixed day's partition.
It can make that Copy wrong or consume storage through repeated appends. It
cannot modify the Library source files; they remain the recovery oracle. This
is an explicit single-tenant prototype tradeoff, not a reversal of product D13
or a multi-tenant authorization scheme. Enabling the shipped product remains
Cosmin's ruling. This prototype uses neither unrestricted `-u` nor a host hook.

## 3. Everything else stays restricted

REPORT.md includes the exact `RAY_FN_RESTRICTED` builtin list before and after,
with all prior entries unchanged and `.db.splayed.append` still restricted.
The request's restricted eval flag remains set throughout, including the append.
There is no temporary unrestricted evaluator. Only trusted C performs the
specific mount replacement. Host-function registration and execution are untouched.
Tests deny set/function binding, exec, exit, arbitrary file read/write, generic
append/set, other date/root/partition and nested/indirect attempts, then prove
the connection is still usable and restricted after the permitted append.

Here arbitrary file read/write means the existing `read`, `read-bytes`, `write`
and `write-bytes` entry points. The baseline already allows caller-selected
database reads via `.db.splayed.get` and `.db.parted.get`; this capability does
not widen them and cannot claim they were previously sandboxed. The denial
test includes a positive baseline database-read control to make this limitation
visible. Same-user filesystem races are outside the launch trust boundary.

Counterexamples/tests: changing the date or adding a path argument must return
`access` (denial table); a launch root containing a partition/symbol escape link must be rejected
before serving; a forbidden call immediately following append must still return
`access` (flag restoration regression); a saved host-hook source diff must be
empty; the parsed restricted-registration lists must match exactly.

## 4. Wire request

A normal synchronous serialized call list carries the builtin symbol, a typed
table value, and a DATE value. Tables use the existing serializer's ordered
column representation, not CSV or interpolated source text. The server's
existing inbound frame cap remains in force. The exact encoded minute size
and cap are recorded from the actual nine-column payload; 1.2 MB in the brief
is an estimate, not a guaranteed size. An oversized inbound header must be rejected before its body is accepted;
`checks.py` sends cap+1 and requires connection close. The existing decoder
remains unchanged; this suite does not prove exhaustive malformed-frame safety.

## 5. Durability and visibility

C2's six-section contract is the storage contract, including commit-uncertain
errors and snapshot readers. After append the engine reopens the configured
parted root and replaces `quotes_1m` before successful response. A subsequent
query on the same restricted connection sees the extra rows. If remount fails
after publish, the error must disclose that commit may already have happened.
The integration test uses Northline's supervisor and wire codec in an isolated
Northline worktree, with the certified crate fixtures and candidate binary.

Counterexamples/tests for sections 1, 2, 4 and 5: `checks.py` sends past/future
dates, paths, disabled configuration and an escape symlink; checks all nine
fields of a real minute; checks cap+1 rejection and the encoded request size;
then forces the post-publish remount to fail by moving the root at the observed
debug stop and requires `commit`, old held binding and newly persisted rows.
The same-connection supervisor test repeats the allowed append and forbidden
operations through Northline's actual request queue. No test establishes a
quota, protection against same-user filesystem mutation, physical power-loss
recovery, or exhaustive absence of evaluator authorization bugs.
