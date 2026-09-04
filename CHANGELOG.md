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

Nightshift only. 24x7 keeps the state of 1.0.0: no isolation check, no
measurement, no receipt.

### Added

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
  ends up in the receipt.
- `nightshift-cost.sh`: reads the `stream-json` output, sums the `usage`
  fields per model, estimates the dollars from a price table dated
  2026-06-24, and writes a running total. At `NIGHTSHIFT_BUDGET_USD`
  (default 25.00) or `NIGHTSHIFT_BUDGET_TOKENS` it terminates the Claude
  process and its children, and the run ends with exit code 9. Without `jq`
  or with an unknown format it measures nothing and lets the run continue.
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

### Changed

- `nightshift-run.sh` takes the project path from `NIGHTSHIFT_PROJEKT` and
  falls back to the path from generation time. Without this the container
  would `cd` into the host path, which does not exist there.
- The `sandbox-exec` profile is documented as the macOS option instead of the
  recommendation. The invocation now sets `NIGHTSHIFT_SANDBOXED=seatbelt`, so
  the runner can tell it apart from an unfenced run.
- The Linux recipe with a dedicated user account works now: it passes
  `NIGHTSHIFT_PROJEKT` and the explicit opt-out. It stays documented as
  permission scoping, not isolation.

### Fixed

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
