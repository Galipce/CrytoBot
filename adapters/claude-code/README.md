# Adapter: Claude Code

Install: `./scripts/init claude-code` — copies `CLAUDE.md` and `.claude/` to the repo root.

What it adds on top of the core:

- **Segment commands** (`.claude/commands/`): `/analyze`, `/plan`, `/build`, `/review`, `/verify`
  — one per segment of `workflows/segments.md`. Each checks its entry condition (spec
  `Status: Approved`, plan `Approved by / on`, build evidence, triage), does its segment, and
  **always stops** with a handoff line naming the next command. Handoffs travel through files.
- **Chainer**: `/new-feature` reads the Mode from `AGENTS.md`. In `lite` it runs the segments in
  order and asks at each gate (spec, plan, triage, ship); in `strict` it refuses and redirects to
  the segment commands, one role per session. The rule:
  *Segments always stop; /new-feature flows only as far as the mode allows.*
- **Change requests**: `/change` — runs the triage rubric of `workflows/change-request.md`
  (bug / trivial / change) with a reasoned verdict, then the lane the behavior demands; in strict
  mode it stops after the mini-spec, in lite it chains with gate approvals.
- **Other commands**: `/bootstrap`, `/fix-bug`, `/refactor`, `/adr`, `/recover` — each loads the
  matching workflow and honors the operating mode. All commands are thin by design: they point to
  `workflows/` and `prompts/`, they don't restate them.
- **Read-only reviewer subagent** (`.claude/agents/reviewer.md`): the "producer never verifies its
  own work" rule at the tool level — the subagent has no Edit/Write tools. Bash stays so it can run
  `scripts/check`, and it is instructed never to write; CI review gates are the backstop.
- **Permission denies** (`.claude/settings.json`): force push, hard reset, `git rebase`, `rm -rf`
  blocked by the tool, not by politeness.
- **Immutability hook** (`.claude/hooks/protect-shipped.sh`): Edit/Write/MultiEdit/NotebookEdit
  under `specs/done/` are physically rejected. A shell redirect is not caught — the CI gate
  (`scripts/doctor --strict`) and review are the backstop.
- **Handoff note hook** (`.claude/hooks/handoff-note.sh`, `Stop`): at the end of every turn it
  writes `.claude/handoff.local.md` — date-time, branch, last commit, active specs and their
  `Status`, the matching plan's `Approved by / on` line and first unfinished step, uncommitted
  changes. Derived from files and git only (never the conversation), untracked
  (`.claude/.gitignore`), written by a background job so the turn waits only for its start (hook
  capped at 2 s), and a failure never blocks the turn. Another tool resumes
  from it (`adapters/antigravity/README.md`).

All defaults are adjustable — see "Adapting it" in the root README.
