# C8: one launch-bound write on a restricted connection

The five-section [contract](CONTRACT.md) passes the bounded tests. Runtime code is `d265e681` on `series/10-restricted-append` in `/home/gunazzi/lead-linux/rayforce-c8`, based on C2 `3a96cc0a`. The contract was committed before C8 code at `76181b1e`. Northline's isolated worktree `/home/gunazzi/lead-linux/northline-c8`, branch `codex/proto-c8-restricted-append`, commit `449ef73cc`, adds typed requests to the existing supervisor queue. Neither branch is merged into the product.

## Refutations and bound of damage

- Restricted mode was never a filesystem read sandbox: the baseline allows `.db.splayed.get` and `.db.parted.get` on caller-supplied paths. `checks-2` and `checks-tsan` explicitly demonstrate that database-read control even with the append capability disabled. Generic file read/write remains denied. The stronger claim “cannot read any other file” is unproven and contradicted for valid databases.
- A successful allowed write must not imply temporary unrestricted evaluation. No eval-flag setter is used by the capability; the existing IPC request code retains the restricted flag throughout. Only trusted C refreshes `quotes_1m`.
- Sending the real nine-column minute as a typed table takes **2,205,864 bytes**, not the brief's approximate 1.2 MB. The server cap is **268,435,456 bytes**: this payload is about 0.82% of it. A cap+1 header is rejected before a body is supplied. A single enormous inline text expression hit `limit` in the preliminary run, and its failed time is not reported.
- Typed text may append arbitrary valid rows when enabled, including through an already-allowed database getter. It can corrupt the day's derived Copy and consume disk by repeated appends, including retained generations and shared sym growth. The Library remains the recovery oracle. There is no quota or hostile same-user filesystem-race guarantee. Product D13/RELIABILITY 61 still need Cosmin's adoption ruling.

## Contract-to-test argument

| Section | Counterexample | Executed test / result |
|---|---|---|
| 1. Capability surface | Peer supplies another date/root/path, or launch escapes through a symlink | `checks.py` denial table, disabled configuration and escape-link launch; pass |
| 2. Newly permitted damage | Valid append changes old held data, Library or unrelated write targets | Real minute's nine fields match; held count remains two; write/exec marker files absent; pass within the launch trust model. No disk quota is established |
| 3. Everything else restricted | Append clears eval flag or removes a restricted registration | Before/after parsed lists equal; IPC and host-function source diffs empty; forbidden calls before and after append return `access`; pass |
| 4. Wire request | Wrong column encoding or oversized input accepted | Python codec and Northline's independent Rust codec both send the real table; every returned field matches; cap+1 closes; pass |
| 5. Durability and visibility | Ack arrives with stale `quotes_1m`, or remount failure hides publication | Same socket immediately sees new count; held binding unchanged. Stop after publication, temporarily move root, resume: `commit`, old binding retained, persisted new rows reopen; pass. Physical power loss unproven, as in C2 |

The source of authorization is the trusted launch's `--append-root ROOT --append-date YYYY.MM.DD`. Both plus a listener are required. It binds an existing canonical root, fixed day and `quotes_1m`; missing authorization returns `access`. The peer passes only TABLE and DATE. `src/store/appendcap.c:52` refreshes the mount; `:64` binds configuration; `:101` checks each call and invokes C2 directly. `src/app/main.c:436` configures it after the trusted script and before serving requests. Date parsing rejects invalid calendar dates by round trip. These checks are not an `openat`/directory-fd sandbox against same-user path replacement.

## Denial table

Every following result is asserted on the same restricted connection used for the permitted typed append, with usable `(+ 1 2)` afterward. Exact source expressions are in `prototypes/c8/checks.py`.

| Attempt | Observed answer |
|---|---|
| set | `access` |
| bind function | `access` |
| exec | `access` |
| exit | `access` |
| read | `access` |
| read-bytes | `access` |
| write | `access` |
| write-bytes | `access` |
| other root | `access` |
| other partition | `access` |
| past date | `access` |
| future date | `access` |
| path argument | `access` |
| path as table | `access` |
| indirect exec | `access` |


Disabled capability also answers `access`. A symlinked partition/sym launch is refused before serving. The post-commit remount-failure test requires `commit`, and a subsequent `set` still returns `access`. The positive database-read control is intentionally allowed and reported above.

## Restricted registration list before and after

Baseline is C2 `3a96cc0a`; after is C8 `d265e681`. All 64 prior RESTRICTED registrations are unchanged. The one new registration is `.db.append_today`; `.db.splayed.append` remains RESTRICTED. `src/core/ipc.c:1145-1178` sets/restores the request flag, unchanged. Host registration/dispatch source in `src/lang/env.c`, `src/lang/syscmd.c`, `src/ops/system.c` and IPC is unchanged. Existing host-hook tests remain in the full suite. The append builtin is not marked pure or routed through a host hook.

| Builtin | Before C8 | After C8 |
|---|---|---|
| `set` | RESTRICTED | RESTRICTED |
| `update` | RESTRICTED | RESTRICTED |
| `insert` | RESTRICTED | RESTRICTED |
| `upsert` | RESTRICTED | RESTRICTED |
| `delete` | RESTRICTED | RESTRICTED |
| `read-csv` | RESTRICTED | RESTRICTED |
| `write-csv` | RESTRICTED | RESTRICTED |
| `.csv.read` | RESTRICTED | RESTRICTED |
| `.csv.splayed` | RESTRICTED | RESTRICTED |
| `.csv.parted` | RESTRICTED | RESTRICTED |
| `.csv.write` | RESTRICTED | RESTRICTED |
| `.parquet.scan` | RESTRICTED | RESTRICTED |
| `.parquet.meta` | RESTRICTED | RESTRICTED |
| `.parquet.read` | RESTRICTED | RESTRICTED |
| `.parquet.each` | RESTRICTED | RESTRICTED |
| `.parquet.splayed` | RESTRICTED | RESTRICTED |
| `.parquet.parted` | RESTRICTED | RESTRICTED |
| `read` | RESTRICTED | RESTRICTED |
| `read-bytes` | RESTRICTED | RESTRICTED |
| `write` | RESTRICTED | RESTRICTED |
| `write-bytes` | RESTRICTED | RESTRICTED |
| `load` | RESTRICTED | RESTRICTED |
| `exit` | RESTRICTED | RESTRICTED |
| `.db.splayed.set` | RESTRICTED | RESTRICTED |
| `.db.splayed.append_proto` | RESTRICTED | RESTRICTED |
| `.db.splayed.append` | RESTRICTED | RESTRICTED |
| `.db.parted.fill` | RESTRICTED | RESTRICTED |
| `.db.parted.drop` | RESTRICTED | RESTRICTED |
| `alter` | RESTRICTED | RESTRICTED |
| `.sys.exec` | RESTRICTED | RESTRICTED |
| `.sys.cmd` | RESTRICTED | RESTRICTED |
| `.sys.listen` | RESTRICTED | RESTRICTED |
| `.sys.loadfn` | RESTRICTED | RESTRICTED |
| `.os.getenv` | RESTRICTED | RESTRICTED |
| `.os.setenv` | RESTRICTED | RESTRICTED |
| `.ipc.open` | RESTRICTED | RESTRICTED |
| `.ipc.close` | RESTRICTED | RESTRICTED |
| `.ipc.send` | RESTRICTED | RESTRICTED |
| `.ipc.post` | RESTRICTED | RESTRICTED |
| `.ipc.txlimit` | RESTRICTED | RESTRICTED |
| `.mc.pub` | RESTRICTED | RESTRICTED |
| `.repl.connect` | RESTRICTED | RESTRICTED |
| `.repl.disconnect` | RESTRICTED | RESTRICTED |
| `.log.open` | RESTRICTED | RESTRICTED |
| `.log.write` | RESTRICTED | RESTRICTED |
| `.log.replay` | RESTRICTED | RESTRICTED |
| `.log.roll` | RESTRICTED | RESTRICTED |
| `.log.snapshot` | RESTRICTED | RESTRICTED |
| `.log.close` | RESTRICTED | RESTRICTED |
| `.log.purge` | RESTRICTED | RESTRICTED |
| `.time.timer.set` | RESTRICTED | RESTRICTED |
| `.time.timer.del` | RESTRICTED | RESTRICTED |
| `del` | RESTRICTED | RESTRICTED |
| `.sys.querylog.enable` | RESTRICTED | RESTRICTED |
| `modify` | RESTRICTED | RESTRICTED |
| `rule` | RESTRICTED | RESTRICTED |
| `dl-add-edb` | RESTRICTED | RESTRICTED |
| `dl-stratify` | RESTRICTED | RESTRICTED |
| `dl-eval` | RESTRICTED | RESTRICTED |
| `dl-free` | RESTRICTED | RESTRICTED |
| `hnsw-free` | RESTRICTED | RESTRICTED |
| `hnsw-save` | RESTRICTED | RESTRICTED |
| `hnsw-load` | RESTRICTED | RESTRICTED |
| `.graph.free` | RESTRICTED | RESTRICTED |
| `.db.append_today` | absent | NONE; launch capability required |


## Wire and supervisor

The request is a normal synchronous call list: SYM `.db.append_today`, TABLE (ordered column names and typed columns), DATE (days since 2000-01-01). No serializer or protocol version changed. Server inbound checks remain `src/core/ipc.c:1093` and the existing decompression bound. `SidecarHandle::append_today(Table, date, wake)` queues `Value::List`; the supervisor sends it with `Connection::evaluate_value`. Ordinary Question Window source continues through its existing verbose text path. The integration fixture launcher adds the two capability flags while the real supervisor retains its loopback listener, fresh password, `-U`, stdin and shutdown policy.

## Gates before measurement

- Optimized fork `make check`: **6,575 passed, 15 skipped, zero failed**, `full-check.log`, `rayforce-c8/build/check/20261101T152502-3181634`; 16 test processes, two runtime workers each.
- Linux TSan filters: product append 2/2; pool 116/6 skipped; heap 148/11; parallel 58; stress 39; parted concurrent mounts 2. Zero failures/warnings, `tsan-1/results.json`. Four configured workers, observed changing build-lane affinities recorded per filter.
- New restricted IPC contract against the TSan server: `checks-tsan/results.json`, all denials, field checks, cap rejection, disabled capability and post-publish remount failure passed, no TSan warning in server logs.
- `cargo nextest run -p northline-rayforce`, through the worktree's serial build wrapper: **74 passed, zero skipped**, `nextest.log`. Candidate was `rayforce-c8/rayforce.fast`; certified futures fixture was the existing `captures/frozen/futures-ui-replay/glbx-20260820-1331-1431-es-trades.dbn.zst`. The new test sends 26,098 rows through the actual supervisor and compares every returned column.
- Correctness runs used uncontrolled cache/load; they are not performance numbers. `BUILD-MANIFEST.json` records binary hashes. Initial namespace-count expectations were updated from two to three `.db` members before the passing full run. The TSan build-only zero-match command is not counted as a passed test.

## Measured same-connection path

Medians (minimum–maximum), **n=3**, typed/file-backed-text then reversed, then forward, one exclusive serial window. **16 workers**, CPUs **24-31,56-63**, Linux btrfs, actual destination files warmed before launch, **mixed load1 2.198–2.422**, release SHA-256 **`8991ff33a4b6a8f5f291a8f5987e5c231a6fb82de2726ee2fdb72904ccf355e4`** for every cell. The base/tail are C2's disjoint **11,033,803 + 26,098** rows. `benchmark-2/results.json` stores all samples and conditions.

| Request path | Append acknowledgement wall ms | Next count query ms | Append through next query ms | Server peak RSS KiB |
|---|---:|---:|---:|---:|
| typed | 568.925 (548.500–590.745) | 0.095 (0.084–0.100) | 569.009 (548.595–590.846) | 262,620 (261,684–264,904) |
| file-backed-text | 573.253 (544.115–587.352) | 0.089 (0.083–0.091) | 573.341 (544.205–587.435) | 252,116 (243,632–254,684) |


Wall begins just before request encoding/send and ends at acknowledgement or the immediately following count reply; server launch, payload construction and fixture copy are outside. The typed payload is already encoded in this harness, so the typed wall excludes Rust table encoding; the supervisor test separately covers that codec without a timing claim. The server peak is `/proc/PID/status` VmHWM after reset before append and before large verification reads. Every sample checks the changed count, unchanged held count, continued denial of `set`, and all nine tail fields.

The file-backed expression is the small `(.db.append_today (.db.splayed.get tail sym) date)` control. It supplies the identical minute via an existing allowed database read; it has a different input route, not a claim about inline text parsing or equal network bytes. Typed appends use no server-side minute file. `benchmark-1` preserves the rejected huge inline-expression attempt and is excluded.

Checklist: actual work and success are asserted; boundaries, load, cache and hashes are explicit; all six appends verify. C2's separate profile identifies the shared STR/SYM storage reconstruction work, but this run did not independently profile IPC encoding or the client. Three trials satisfy the brief; no performance winner or hardware minimum is inferred.

## What this run could not measure

A hostile same-user filesystem race; exhaustive evaluator/decoder authorization safety; arbitrary malformed frames; physical power loss or torn writes; sustained repeated appends, resource quotas or reclamation; exactly-once retries after disconnect/`commit`; multiple simultaneous peers; complete Terminal UI latency; timed Rust table encoding; a full inline-text minute bypassing the parser limit; or independent cold-device behavior. Existing arbitrary database reads remain outside a filesystem sandbox. The fork capability is disabled unless explicitly configured; the installed product binary and pin remain unchanged.
