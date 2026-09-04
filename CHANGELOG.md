# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), the numbering follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Where the version lives:** the `VERSION` file in the repository root is the
only place it is maintained. `scripts/build_release.py` reads it, the release
workflow refuses to publish when the tag and `VERSION` disagree, and CI checks
that this file and the landing page footer name the same version. A release is
cut by tagging `v` plus the content of `VERSION`.

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
