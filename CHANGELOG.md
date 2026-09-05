# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), the numbering follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Where the version lives:** the `VERSION` file in the repository root is the
only place it is maintained. `scripts/build_release.py` reads it, the release
workflow refuses to publish when the tag and `VERSION` disagree, and CI checks
that this file and the landing page footer name the same version. A release is
cut by tagging `v` plus the content of `VERSION`.

## [Unreleased]

Cost governor and receipt are still Nightshift only; 24x7 keeps the state of
1.0.0 there. Container isolation and the path barrier of the PreToolUse hook
are in both.

### Added

- A second `PreToolUse` entry in both generated setups:
  `"matcher": "Write|Edit|MultiEdit|NotebookEdit"`. It resolves the target path
  of the call. `~/` becomes the home directory, `.` and `..` are resolved, and
  a relative path is resolved against the working directory Claude Code sends
  with the call. Every target outside the project or workspace directory ends
  with exit code 2. The root comes from `NIGHTSHIFT_PROJEKT` or
  `CLAUDE_24X7_WORKSPACE` at run time, so the same hook fences the run inside
  the container, where the project sits at `/project`. Without `jq`, and for an
  input without a path, it blocks instead of waving the call through.
  `.claude/settings.json` is blocked inside the directory too: a run that may
  rewrite its own barrier has none. Until now the hook carried
  `"matcher": "Bash"` alone, and an unattended run could write any file on the
  disk without the protection layer seeing it.
- `gemeinsam.py` in the repository root: the block pattern and both hook bodies
  live there once instead of twice, and both generators read them. The file
  ships inside both `.skill` artifacts next to `build_zip.py`, and a test
  unpacks an artifact and runs the generator from that location, because the
  repository layout and the installed layout are two different places.
- `tests/test_pfad_schranke.py`: 14 write targets that must be blocked and 9
  that must pass, per skill, driven as real tool calls through the hook command
  taken out of the generated `settings.json`. Plus `Edit`, `MultiEdit` and
  `NotebookEdit` on both sides of the boundary, an input without a path, and a
  run with `jq` removed from `PATH`. New CI step.
- A section in both generated READMEs and in README.md that names what the path
  barrier does not cover: writes performed by a Bash command, every read,
  symlinks inside the directory pointing out, `/tmp` versus `/private/tmp`,
  tools from MCP servers, and a `.claude/settings.json` that was never
  installed.
- Container isolation for 24x7: `Dockerfile`, `docker-compose.yml` and
  `24x7-docker.sh` in the generated setup. The workspace is mounted as
  `/workspace` and is the only path from the host; the home directory lives in
  a named volume; the runner hangs in an internal network whose only bridge
  outward is the same allowlist proxy Nightshift uses. Root filesystem
  read-only, all capabilities dropped, `no-new-privileges`, non-root user.
  Unlike the Nightshift script this one starts a daemon: `up -d`, and
  `./24x7-docker.sh --logs` follows the log. Tasks keep arriving in `inbox/`
  on the host, because that directory is the mount.
- Isolation detection in `runner.sh`, the same probe Nightshift runs:
  `docker`, `seatbelt` or `keine`. Without isolation the runner ends with exit
  code 3 before the task loop starts; `CLAUDE_24X7_ALLOW_UNSANDBOXED=1` is the
  documented way past it, `CLAUDE_24X7_SANDBOXED` is a cross-check that grants
  nothing. Both checks sit before the `trap`, because the cleanup handler ends
  with `exit 0` and would swallow the 3.
- `WORKSPACE` in `runner.sh` and `runner-bg.sh` now comes from
  `CLAUDE_24X7_WORKSPACE` and falls back to the generated path. The container
  sets it to `/workspace`, and the path barrier of the hook reads the same
  variable, so both agree on where the workspace is.
- A restart policy in both watchdogs. `NIGHTSHIFT_WATCHDOG_AKTION` and
  `CLAUDE_24X7_WATCHDOG_AKTION` take `melden` (the old behaviour and still the
  default), `beenden` (TERM to the PID in the PID file, KILL after
  `..._WATCHDOG_FRIST` seconds, then the watchdog exits) or `neustart` (the
  same, then start the run again, at most `..._WATCHDOG_NEUSTARTS` times).
  TERM before KILL because both runners trap it: Nightshift ends Claude's
  process group, 24x7 moves the running task to `failed/`.
  A run that ended on its own is never restarted. The watchdog restarts only
  what it just terminated itself and recognises that by a live PID, so a
  budget stop cannot be undone by a restart, and neither can a crash or a
  finished run. The roadmap asked for exactly that guarantee; it now follows
  from the order of operations instead of from a second mechanism.
  `..._PIDDATEI` and `..._HEARTBEAT` make both paths overridable, which is
  what allows the reaction to be driven in CI without touching a real run.

- `Dockerfile` and `docker-compose.yml` in the generated Nightshift setup,
  plus `nightshift-docker.sh` to build and run it. The container mounts the
  project as `/project` and nothing else from the host; the home directory
  lives in a named volume, so `~/.claude` of the host stays outside. The
  runner hangs in an internal network whose only bridge outward is a tinyproxy
  with an allowlist: `api.anthropic.com` passes, everything else gets a 403.
  Root filesystem read-only, all capabilities dropped, `no-new-privileges`,
  non-root user in both images.
- Isolation detection in `nightshift-run.sh`: `docker`, `seatbelt` or `keine`.
  Without isolation the run ends with exit code 3;
  `NIGHTSHIFT_ALLOW_UNSANDBOXED=1` is the documented way past it. The state
  ends up in the receipt. It is measured, not declared — see the entry under
  Fixed.
- `nightshift-cost.sh`: reads the `stream-json` output, sums the `usage`
  fields per model, estimates the dollars from a price table dated
  2026-06-24, and writes a running total. At `NIGHTSHIFT_BUDGET_USD`
  (default 25.00) or `NIGHTSHIFT_BUDGET_TOKENS` it terminates Claude's
  process group, and the run ends with exit code 9. Without `jq` or with an
  unknown format it measures nothing and lets the run continue.
- `nightshift-receipt.sh`: writes `nightshift-receipts/<run>/receipt.json`
  and `receipt.md` from the exit trap, so a crashed run leaves one too. Steps
  done against steps open including the list of open ones, `git diff
  --shortstat`, commit, exit code, isolation, tokens, estimated cost,
  decisions and stall warnings. Fields the run could not determine read
  `"unbekannt"`, never `0` or `null`.
- Tests `tests/test_isolation.py` and `tests/test_kosten_receipt.py`, both in
  CI. They drive `nightshift-run.sh` against a Claude stub, so the abort
  without isolation, the budget stop and the receipt are checked without an
  API call. Validating the generated `docker-compose.yml` needs a Compose
  command and is skipped without one.

- A "Related Projects" section in the README that places
  `moinsen-dev/NightShift`: an independent reimplementation, not a fork, no
  code moved in either direction, therefore no `NOTICE`. It names what that
  implementation does better (`shared/` module, longer blocklist) and where
  its cost tracker does not hold: `CLAUDE_PID` is never assigned, `grep -oP`
  fails on macOS, the sums live in a subshell. Checked against the repository
  on 2026-09-04.

### Changed

- The watchdog counts a zombie as ended. `kill -0` answers yes for a process
  that has exited but not been reaped, so a crashed run whose parent never
  collected it looked alive and the watchdog would never have acted. It now
  asks `ps -o state=` as well; without `ps` the old behaviour stands.

- The 24x7 seatbelt profile is the fixed one. It carried the old
  deny-by-default read rules, under which nothing starts on current macOS
  (`sandbox-exec -f sandbox.sb /bin/echo hi` ended with SIGABRT); Nightshift's
  profile was repaired in 1.0.0 and 24x7's was not. Both now come from one
  template, and the test that starts a program under the profile runs for
  both.
- `Dockerfile`, `docker-compose.yml`, the docker script, the seatbelt profile
  and the isolation check are one implementation in `gemeinsam.py`, filled
  with the names of each skill. The generated Nightshift files are unchanged
  byte for byte; that was the acceptance test for the move.
- `nightshift-run.sh` takes the project path from `NIGHTSHIFT_PROJEKT` and
  falls back to the path from generation time. Without this the container
  would `cd` into the host path, which does not exist there.
- The `sandbox-exec` profile is documented as the macOS option instead of the
  recommendation. The documented invocation is the bare `sandbox-exec -f
  nightshift-sandbox.sb ./nightshift-run.sh`; the runner recognises it from a
  probe instead of an environment variable.
- The Linux recipe with a dedicated user account works now: it passes
  `NIGHTSHIFT_PROJEKT` and the explicit opt-out. It stays documented as
  permission scoping, not isolation.

### Fixed

- **The watchdog looked for the run in a place the runner never wrote to.**
  The new stall reaction reads the PID file from `NIGHTSHIFT_PIDDATEI` or
  `CLAUDE_24X7_PIDDATEI`, while both runners kept writing to a hardcoded
  `/tmp/nightshift.pid` or `/tmp/24x7.pid`. Anyone who set the variable got a
  watchdog that found no PID, reported "no running process" and never acted
  again, on exactly the stall it exists for. Both runners now read the same
  variable and keep the old path as the default, so an operator who sets
  nothing sees no change. A test in `tests/test_watchdog.py` compares the two
  files against each other instead of trusting the intent. The shared path also
  made two runs on one machine impossible: a second project could not start
  while the first held the lock, and a stale file whose PID had been reused by
  an unrelated process blocked every run until someone deleted it by hand.

- **The generated command line was rejected by Claude Code.** `claude -p
  ... --output-format stream-json` without `--verbose` ends with "When using
  --print, --output-format=stream-json requires --verbose" and exit 1 on
  2.1.261. No run started, so budget stop and receipt were only ever proven
  against a stub. `--verbose` is now part of the call in both generators, and
  a run against the real API confirms the field names the counter reads:
  `message.usage.input_tokens` / `output_tokens` and `type: "result"`.
- **The isolation gate was self-declared.** Any value in
  `NIGHTSHIFT_SANDBOXED` passed: `=banane` ran on a bare macOS shell with
  `--dangerously-skip-permissions` and wrote `isolation: banane` into the
  receipt. The runner now probes — `/.dockerenv`, `/run/.containerenv`,
  `/proc/1/cgroup` or an overlay root for the container; an unreadable
  `/Users` next to a readable project for the seatbelt profile. The variable
  is a cross-check: if it disagrees with the measurement, the run ends with
  exit code 3. The tests no longer switch isolation on through it.
- **The seatbelt profile started no program at all.** On Darwin 27,
  `sandbox-exec -f nightshift-sandbox.sb /bin/echo hi` ended with SIGABRT:
  deny-by-default reads exclude the dyld cache on current macOS, and
  `/dev/null` was not writable either. The profile keeps the write fence and
  the home-directory fence, opens reads, and grants the usual devices.
- **A run the counter could not read appeared as a measured zero.** With `jq`
  present and output that is not `stream-json`, the awk END block wrote
  `status: gemessen`, 0 tokens and 0.0000 USD, and `receipt.md` printed
  "0.0000 USD (Status: gemessen)" right above its own note that costs may be
  unknown. Zero usage events now write the unknown state, and the receipt
  prints "unbekannt (Status: unbekannt)". The gap in the test suite is
  closed: the case with `jq` present is covered too.
- **The budget stop did not reliably end the run.** `pkill -P` reaches only
  direct children; a reparented process holding the pipe descriptor kept
  runner and `tee` alive for a measured 2:33 min. Claude starts in its own
  process group (`set -m`) and the counter uses `kill -- -PGID`. After the
  stop marker the runner also enforces a hard deadline
  (`NIGHTSHIFT_STOPFRIST`, 30 s). Measured after the change: the run ends 4 s
  after the stop, with no orphan left.
- **The documented way to end a run had no effect.** `kill $PID` from
  `nightshift-run-bg.sh` and from the PID-lock message left runner and
  `claude --dangerously-skip-permissions` running — measured 19 s later, both
  still alive — because the EXIT trap fires only after the foreground
  pipeline. The pipeline now runs in the background and the runner waits on
  it, so the SIGTERM/SIGINT trap fires immediately; it kills Claude's process
  group first and writes the receipt afterwards. Claude's stdin is redirected
  from `/dev/null` along with it: a background process group reading from the
  terminal would stop on SIGTTIN. Measured on a pseudo-terminal, this version
  does not read stdin in `-p` mode; the redirect takes the case out anyway.
- **The price-table fallback underestimated.** `claude-fable-5-1` with 1M
  tokens each way came to 30.00 USD instead of 60.00, `claude-sonnet-4-6` to
  12.00 instead of 18.00. The table now knows `fable` and `mythos` (10/50)
  and splits `sonnet-4-6` (3/15) from `sonnet` (2/10), first match wins; an
  unknown name costs twice the most expensive known row, because a model
  released after the table's date can be dearer than everything in it.
- **The cost estimate undercounted cached input by 37 percent.** One factor
  of 1.25 covered both cache durations. A real run estimated at 0.1637 USD
  where Claude reported 0.25863. Five-minute cache writes now count 1.25x,
  one-hour writes 2x, and unattributed cache creation counts at the dearer
  rate. The same run now estimates 0.25860 USD.
- `index.html` was truncated mid-attribute in the impressum link, so the last
  paragraph, `</footer>`, `</body>` and `</html>` were missing from the live
  landing page. The dangling link target could not be reconstructed and was
  replaced by a link to the author's GitHub account.

## [1.0.0] - 2026-09-04

First tagged release. Both skills have been installable from a clone for a
while; this release makes them downloadable and closes the defects that made
the documented setup fail on a fresh machine.

### Added

- Release artifacts `nightshift.skill` and `24x7.skill`, built by
  `scripts/build_release.py`. Each one is a ZIP holding a single directory
  named after the skill, with `SKILL.md`, `scripts/build_zip.py`, `LICENSE`
  and `VERSION` in it. `unzip nightshift.skill -d ~/.claude/skills/` installs
  it. Two runs of the script produce byte-identical archives.
- `.github/workflows/release.yml`: a tag matching `v*` builds the artifacts and
  attaches them to the release. The workflow contains no packaging logic, it
  calls the script.
- `VERSION` and this changelog as the version source.
- `NIGHTSHIFT_OUT` and `CLAUDE_24X7_OUT` set where the generators write the
  setup ZIP, which is what makes them testable.
- CI: both generators are compiled and executed under Python 3.9, the block
  patterns of the `PreToolUse` hook run against a table of commands, and the
  release artifacts are built and inspected on every push.

### Fixed

- The Nightshift generator carried a backslash inside an f-string expression.
  That parses only from Python 3.12 on, so on the macOS system Python 3.9 the
  documentation names as the minimum, the file was a syntax error before it ran
  a single line.
- The `PreToolUse` hook let every command through when `jq` was missing. It now
  blocks instead of waving things past.
- The hook's `rm` rule fired on harmless commands such as
  `rm -rf node_modules`, and it missed commands whose arguments were quoted.
- `nightshift-run.sh` swallowed the exit code of the Claude run, so a failed
  run looked like a finished one.
- The 24x7 runner called `timeout`, which macOS does not ship. It now uses
  `gtimeout` when that is present and refuses to start when neither exists.
- The documented install step copied the setup without `.claude/`, so the run
  started with no hooks at all. An existing `.claude/settings.json` is no
  longer overwritten.
- The 24x7 generator built its ZIP at import time and wrote it to a fixed path,
  so every import and every test hit a `FileNotFoundError`. The Nightshift
  generator already had the `__main__` guard.
- README, the four guides and the landing page described the sandbox, the reach
  of the hooks, Linux support, the runbook validation and the install steps in
  ways the code did not back up. Those passages now match the code.
- Both `SKILL.md` files told Claude to copy the generator from
  `/mnt/skills/user/`, a path that exists on claude.ai but not in an
  installation under `~/.claude/skills/`, and neither one named
  `NIGHTSHIFT_OUT` or `CLAUDE_24X7_OUT`, so the run wrote to the read-only
  `/mnt/user-data/outputs/`. The copy step now finds the generator in either
  place, and the variable list names the output path.

[1.0.0]: https://github.com/GodModeAI2025/NightShift/releases/tag/v1.0.0
