# Adapter: Antigravity

Install: `./scripts/init antigravity` — copies the commands, as Antigravity skills, to
`.agents/skills/` in the repo root.

What it adds on top of the core:

- **Pointer: none needed.** Antigravity (`agy`) loads `AGENTS.md` natively as workspace rules.
  This adapter only delivers the commands.
- **Commands as skills** (`skills/<name>/SKILL.md`): the same twelve commands as every other
  adapter — segments `/analyze`, `/anew-plan`, `/build`, `/review`, `/verify`; the chainer
  `/new-feature`; `/change`; and `/bootstrap`, `/fix-bug`, `/refactor`, `/adr`, `/recover`. Each is
  the same pointer as the Codex skill, with `/name` in place of `$name`; the text after the name
  is the argument (`/build 0027`). *Segments always stop; /new-feature flows only as far as the
  mode allows.*
- **PLAN is `/anew-plan`.** Antigravity has a built-in `/plan` ("think and plan carefully") that
  wins over a project skill of the same name — the skill file is never read. Every other command
  keeps its name (spec 0027, A-1).
- **Project-level:** the skills live in the repository (`.agents/skills/`) and travel with it.
  Commit them like any other adapter file.

## The explicit-only gap

Codex can switch implicit invocation off (`agents/openai.yaml`); Antigravity cannot — it may pick
a skill by itself when a request sounds like one. So every description ends with
`Run only when the user types /<name> explicitly.`, and `scripts/doctor` fails on a skill without
it. That sentence is an instruction, not a lock. What actually holds the gates is the same as for
every tool: each segment's entry check reads the files (spec `Status`, the plan's
`Approved by / on`), and CI runs `scripts/doctor --strict`.

## Sharing `.agents/skills/` with Codex

Codex and Antigravity read the same folder. Install one of them: when both are installed, the
first one's files are kept (`init` never overwrites without `--force`), so the second tool finds
skills written for the other — Codex skills say `$plan` and have no `anew-plan`. To switch,
`./scripts/init --force <tool>`; a leftover `.agents/skills/plan/` (Codex) is harmless to
Antigravity, whose `/plan` is built in.

## Resuming Claude's work in Gemini (manual switch)

When Claude's usage runs out, the switch is by hand — nothing detects it:

1. In PowerShell, from any folder: `scripts\gemini-devam.ps1` (blocked by the execution policy?
   `powershell -ExecutionPolicy Bypass -File scripts\gemini-devam.ps1`). It finds `agy` on PATH or
   in `%USERPROFILE%\.gemini\bin\agy.exe` and opens it at the repo root, interactively, in the
   default permission mode — every action asks first.
2. Gemini reads the state from files: branch, active specs and their `Status`, the plan's approval
   line and first unfinished step, `git status`, and `.claude/handoff.local.md` — the note Claude
   Code's `Stop` hook writes after every turn (`adapters/claude-code/README.md`). A missing note, or
   one whose branch or HEAD differs from the current one, is called out as missing or stale.
3. Gemini proposes the next segment with its command and starts nothing until you approve.
   Run the segments as usual; `/review` still runs in a fresh session that never saw the builder.

Commits Gemini prepares carry the signature line defined in `docs/git.md` (Commits); this adapter
only points at it.

From Git Bash, `agy -p "/build 0027"` is rewritten by MSYS path conversion into
`C:/Program Files/Git/build 0027`; set `MSYS_NO_PATHCONV=1` there. PowerShell is not affected.

## Honored procedurally

Antigravity has no read-only reviewer subagent and no hook layer here:
- **Independent review:** run `/review` in a **fresh Antigravity session** that sees only the diff
  and the spec — never the builder's session.
- **Immutable `specs/done/`:** nothing rejects the edit in the tool; `scripts/doctor --strict` in
  CI and the PR template are the backstop.

Antigravity's skill format may change between `agy` versions; if yours differs, adjust only the
files in this adapter — the core never changes.
