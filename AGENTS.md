# AGENTS.md — Project Rules

**CrytoBot** — kişisel, spot-only kripto alım-satım botu: haber takibi, whitepaper analizi (LLM),
teknik analiz/indikatörler → risk onaylı emirler. Python 3.12 modüler monolit, SQLite, ccxt, Claude API.
Para riski taşır: **risk kuralları kâr hedefinin önündedir** (`docs/domain.md`); varsayılan mod paper.

## Operating mode

**Mode: strict** — bootstrap sets `lite` or `strict` (`workflows/README.md`); every workflow honors its gates.
**Start work** with `/new-feature` in lite (it chains the segments and asks at each gate) or with
`/analyze` in strict (one segment per role). Segment commands always stop (`workflows/segments.md`).
**Language: chat=tr · docs=tr** — bootstrap sets `chat=<xx> · docs=<xx>`; protocol fields stay English (`docs/conventions.md`).

## Invariant rules (these survive bootstrap — never delete or weaken them)

1. **No spec, no code.** Every piece of work starts as a spec in `specs/active/` (from `specs/TEMPLATE.md`).
2. **Plan before build.** A human approves the plan before any code is written.
3. **The producer never verifies its own work.** Review and QA run in a separate session or a read-only subagent, working from files (diff + spec), never from the builder's chat.
4. **Evidence over claims.** "Done" requires `scripts/check` green and every acceptance criterion mapped to proof. Never claim completion without showing evidence.
5. **Tests are protected.** Weakening asserts, deleting or skipping tests to get to green is forbidden — always.
6. **Proposal rule.** Every question, option, or finding comes with your own recommendation and rationale. The human decides; nothing is applied without approval.
7. **Shipped specs are immutable.** Files under `specs/done/` are never edited.
8. **Uncertainty is surfaced, not assumed.** On ambiguity or a docs/code conflict: stop and use the matching recovery ramp (`prompts/recovery/`).

## Where things live

| What | Where |
|---|---|
| Architecture & boundaries | `docs/architecture.md` |
| Domain language, business rules (BR-n) & sensitive areas | `docs/domain.md` |
| Coding conventions & known traps | `docs/conventions.md` |
| Testing rules | `docs/testing.md` |
| Security rules (API keys, live mode, Telegram, LLM input) | `docs/security.md` |
| Git & branching rules (trivial changes → mini-spec) | `docs/git.md` |
| Decisions (ADRs) · roles (who may do what) | `docs/decisions/` · `docs/roles/` |
| Specs & plans | `specs/active/` · `specs/plans/` · shipped → `specs/done/` · deferred findings → `specs/backlog.md` |
| Processes & gates · prompts & recovery ramps | `workflows/` · `prompts/` |
| Every command: what it does, where it stops, lite vs strict | `docs/commands.md` |
| The single verification command | `scripts/check` |
