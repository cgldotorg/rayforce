# Contributing to Rayforce

Thanks for helping improve Rayforce. This page covers the one thing that trips
people up most often — **which branch to target** — plus the basics of getting a
change merged.

## Branch model (read this first)

Rayforce uses a two-branch flow:

- **`dev`** — the integration branch and the repository default. **All
  contributions target `dev`.** Open your PR here.
- **`master`** — release-only. The single PR it ever receives is the
  `dev -> master` release PR (titled `vX.Y.Z`), which a maintainer cuts. Direct
  feature/fix PRs against `master` are blocked by the **Version Guard** check.

`dev` is the default branch, so a fresh `git clone` and the "New pull request"
button already point the right way. If you do open a PR against `master` by
mistake, a bot automatically retargets it to `dev` and leaves a note — nothing
for you to fix.

See [RELEASE.md](RELEASE.md) for how releases are cut.

## Opening a pull request

1. Branch off the latest `dev`.
2. Make your change. Keep commits focused; we use
   [Conventional Commits](https://www.conventionalcommits.org/)
   (`feat:`, `fix:`, `perf:`, `docs:`, `refactor:`, `test:`, `chore:`) — the
   release notes are generated from these prefixes, so they matter.
3. Make sure the build is clean and tests pass locally:

   ```sh
   make            # builds (debug: ASan + UBSan)
   make test       # runs the test suite
   ```

4. Open the PR against **`dev`**. CI runs on every pull request (there are no
   push-triggered runs — the PR run tests the exact merge result).

## Local build notes

- Zero external dependencies; C17 toolchain only.
- `make` compiles with `clang` when `CC` is not set, so a machine without clang
  fails at the first compile. `make CC=gcc` (or `CC=gcc` in the environment)
  builds with gcc. The fuzz, TSan, coverage and `compdb` targets use clang
  regardless of `CC`.
- Debug builds enable AddressSanitizer + UndefinedBehaviorSanitizer; warnings are
  errors (`-Werror -Wall -Wextra`). A warning will fail CI, so fix them locally.
- The version reported by a local build is derived from git tags (`0.0.0` on an
  untagged checkout) — never hand-edit a version literal in source.

### Build flavours

Each flavour compiles to its own object files, so they never clobber one another.

| Target | What it produces |
|---|---|
| `make` / `make debug` | default: `-O0 -g` with ASan + UBSan (the flavour tests run under) |
| `make release` | `-O3 -march=native` with FP-reassociation flags |
| `make hardened` | the cloud tier: release optimisation, but keeps `-g`/frame pointers and links `-rdynamic` so the crash handler (`src/core/crash.c`) prints a symbolized backtrace; defines `RAY_HARDENED` (keeps cheap invariant checks live) |
| `make tsan` / `make tsan-test` | ThreadSanitizer build (clang; mutually exclusive with ASan) — see below |
| `make coverage` | clang source-based coverage → `coverage_html/` |
| `make compdb` | `compile_commands.json` for editors/analyzers |

## Tests

### Parallel local checks (Linux/POSIX)

`make check` builds a separate `-O1 -g -march=native` test profile with DEBUG,
ASan and UBSan enabled, then runs the complete default inventory through CTest.
It requires Python 3.9+ and CTest (from CMake); ccache and LLVM lld are used when
available. The ordinary `make test` remains the serial, `-O0` debugging/CI path.
CTest fits this harness because it already enumerates executable test cases;
no conversion of the existing C or `.rfl` assertions to LLVM lit is needed.

```sh
make check                                    # full C, RFL and equivalence suite
make check CHECK_ARGS='-f store/ -f equiv/store/'
make check CHECK_ARGS='-j 16 --build-jobs 32 --cores 2'
make build-local                              # cached native release build
make build-local BUILD_ARGS='--march x86-64-v3' # portable AVX2 release build
make build-local BUILD_TARGET=debug
make build-local BUILD_TARGET=lib             # incremental static library
python3 scripts/test_check.py                  # runner isolation/cleanup checks
```

On the 32-core/64-thread Threadripper PRO 5975WX, defaults are 32 compilation
jobs, 32 test processes and two runtime workers per process. CPU affinity and
available RAM can reduce the job counts; eight GiB is reserved for other work.
Use explicit job counts to benchmark alternatives. Each test may override its
runtime pool for its own assertions. `--no-build` reuses existing binaries;
`--build-only` builds without testing; `--optimization 0|1|2` changes the check
profile. Native binaries are for this machine, not redistribution.

Each case gets its own working directory and short scratch root under
`~/.cache/rft`. Fixtures use the home filesystem instead of filling `/tmp`.
Fixed-port and server-spawning groups serialize behind a CTest resource lock.
Cooperating `make check` and `make build-local` runs across worktrees share a
machine-level reservation, so they cannot each consume the full CPU budget.
Raw `make test` does not participate; do not run it alongside `make check`.
Timeouts and interrupts terminate each test's process group, including servers.

Full logs, the exact selected inventory, JUnit results and a timing summary are
saved in `build/check/<timestamp>-<pid>/`. Missing, duplicate and zero-test
results fail the run. Large tests remain opt-in (`CHECK_ARGS='-f large/'`),
and platform-dependent skips stay visible. Golden-file updates belong in the
serial runner. Historical timings schedule expensive cases early, and each
source change only rebuilds its dependencies. ccache is shared across
worktrees at `~/.cache/rayforce-ccache` with a default ten-GiB limit.

Debug, release and hardened executables retain separate outputs before
selecting `rayforce`, avoiding unnecessary relinks when switching profiles.
Compiler/flag stamps invalidate objects when the compiler or target CPU changes.

The 2026-11-01 machine check completed 6,569 cases with 15 environment-dependent
skips and zero failures in 101.34 seconds. A full rebuild of cached sanitizer
objects took 2.18 seconds; unchanged build profiles took about half a second.
The initial 32-versus-64 process comparison favored 32 (128.58 versus 140.70
seconds); narrowing unnecessary network locks then reduced the 32-process run
to 101.34 seconds. Counts include the original pool-clamp checks split into
27 separately scheduled cases. See [measurement data](docs/check-throughput-20261101.json).

### Test sources

Behavioural tests live under `test/rfl/<group>/<name>.rfl` and are
auto-discovered. Add or update a `.rfl` test alongside any behaviour change. Run
a focused subset with:

```sh
./rayforce.test -f <substring>
```

A `.rfl` file that needs a POSIX shell or filesystem (fixtures built or
checked through `.sys.exec`, `/proc`, `/dev/tcp`, …) carries the line
`;; @requires: posix`; on Windows the runner reports it as `SKIP` rather
than running it. C tests use `#ifndef RAY_OS_WINDOWS` / `SKIP(...)` for the
same purpose. Prefer the shell-free helpers `ray_test_rm_rf` /
`ray_test_mkdir_p` (`test/test.h`) over `system("rm -rf …")` in C tests.

### Windows

Build with the MSYS2 CLANG64 (or MINGW64) toolchain — `pacman -S
mingw-w64-clang-x86_64-clang make` — from an MSYS2 shell or with
`C:\msys64\clang64\bin` and `C:\msys64\usr\bin` on `PATH`:

```sh
make            # debug build (ASan + UBSan)
make test
make release
```

The debug binaries load the ASan runtime DLL from `clang64\bin`, so keep it on
`PATH` when running them.

## Stability tooling

Beyond the ASan/UBSan test run, the repo carries a stability toolset. These
gate CI (fuzz smoke + TSan on every PR) and run deeper overnight.

Each PR is built with these compilers (`.github/workflows/ci.yml`): gcc for
the Ubuntu debug and release legs, clang for the macOS debug and release
legs, upstream Clang 23 from apt.llvm.org for the Ubuntu `clang-current` test
leg, and the Ubuntu runner's `clang` for the NDEBUG, fuzz-smoke and TSan
legs.

- **Fuzzing** (Linux + clang): coverage-guided targets under `fuzz/` cover the
  parser, numeric scanners, the binary wire/journal decoder, and the sandboxed
  evaluator, CSV, and journal-replay paths. `make fuzz-smoke` is the PR gate;
  `make fuzz-<target> FUZZ_RUNTIME=<secs>` runs one locally. See
  [`fuzz/README.md`](fuzz/README.md), including the crash-triage workflow.
- **ThreadSanitizer**: `make tsan-test TSAN_FILTER=<pool|heap|parallel|stress>`
  runs the concurrency suites under TSan at 4 cores. Every entry in
  `.tsan-suppressions` must justify why the report is benign.
- **Static analysis** (advisory): `make tidy` (clang-tidy, correctness-only
  checks) and `make cppcheck`.
- **Nightly** (`.github/workflows/nightly.yml`): deep randomized stress, the full
  suite under TSan, long fuzz runs, and a server soak (`scripts/soak.sh`) that
  kill/restarts the server and watches resident memory for leaks.
