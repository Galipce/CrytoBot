# Backlog — deferred findings

Findings a human triaged as **defer**: real, but fixed later by decision (`workflows/feature-development.md`,
step 7). Nothing lands here without that decision; noise is rejected in the triage record, not parked here.

- One entry per finding, newest last. Delete the entry in the commit of the work that closes it.
- An entry that grows into new behavior becomes a spec (`specs/active/`), not a fix.

<!-- Format (labels stay English):
- **B-<n>** — <finding, one line> — Source: spec <NNNN>, review round <n> (<file:line>) — Severity: <…>
  — Recommendation: <the reviewer's action> — Deferred by: <name>, <YYYY-MM-DD>, <why>
-->

- **B-1** — Araç öz-testlerinde zaman aşımı yalnızca doğrudan çocuk `sh`'yi öldürüyor; iç içe `sh -c` altındaki
  pytest/mypy süreçleri (Windows'ta her durumda) arkada kalabilir — Source: spec 0001, review round 1
  (`tests/tooling/conftest.py:44-55`) — Severity: Low — Recommendation: alt süreci kendi süreç grubunda başlat,
  zaman aşımında ağacı sonlandır (POSIX `start_new_session=True` + `os.killpg`; Windows
  `CREATE_NEW_PROCESS_GROUP` + `taskkill /T /F`) — Deferred by: Galip Badem, 2026-10-29, yalnızca >180 s zaman
  aşımı yolunda tetikleniyor, hiçbir kriteri bozmuyor; platforma özgü süreç yönetimi ayrı ve dikkatli iş.
