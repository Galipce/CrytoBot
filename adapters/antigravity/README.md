# Adapter: Antigravity

Install: `./scripts/init antigravity` — copies the commands, as Antigravity skills, to
`.agents/skills/` in the repo root.

What it adds on top of the core:

- **Pointer: none needed.** Antigravity (`agy`) reads `AGENTS.md` natively. This adapter only
  delivers the commands.
- **Commands as skills** (`skills/<name>/SKILL.md`): the same twelve commands as every other
  adapter — segments `/analyze`, `/anew-plan`, `/build`, `/review`, `/verify`; the chainer
  `/new-feature`; `/change`; and `/bootstrap`, `/fix-bug`, `/refactor`, `/adr`, `/recover`. Each is
  the same pointer as the Codex skill, with `/name` in place of `$name`. *Segments always stop;
  /new-feature flows only as far as the mode allows.*
- **PLAN is `/anew-plan`.** Antigravity has a built-in `/plan` ("think and plan carefully") that
  wins over a project skill of the same name — the skill file is never read. Every other command
  keeps its name (spec 0027, A-1).
- **Project-level:** the skills live in the repository (`.agents/skills/`) and travel with it.
  Commit them like any other adapter file.
