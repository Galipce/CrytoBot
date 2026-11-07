"""Spec 0027 AC-9: Claude Code'un Stop hook'u her turun sonunda devir notunu yazar.

Hook geçici bir git deposunda (depo dışında) gerçek çıktısı ve çıkış koduyla sınanır.
"""

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "adapters" / "claude-code" / ".claude"
HOOK = TEMPLATE / "hooks" / "handoff-note.sh"
CHAT = "SOHBET-METNI-BURADA-OLMAMALI"
TIMEOUT_S = 60

PLAN = """# Plan 0042 — demo

- Spec: `specs/active/0042-demo.md`
- Status: Approved
- Approved by / on: Test Kişi, 2026-11-07

## Ordered steps
1. **Birinci adım.** Ayrıntı.
   `feat: one [plan 0042/1]`
2. **İkinci adım.** Ayrıntı.
3. Üçüncü adım, kalın başlıksız.

## Risks & open questions
1. Bir risk — adım değil.
"""


def _sh() -> str:
    sh = shutil.which("sh")
    assert sh, "sh is required (Git Bash on Windows)"
    return sh


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_S,
        check=True,
    )
    return result.stdout


def _hook(
    project_dir: Path, cwd: Path, *args: str, wait: bool = True
) -> subprocess.CompletedProcess[str]:
    """Şablondaki hook'u Claude Code gibi çalıştırır: proje dizini ortamda, tur verisi stdin'de.

    Hook notu arka planda yazar ve hemen döner; wait=True iken not yeniden yazılana dek beklenir.
    """
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    note = project_dir / ".claude" / "handoff.local.md"
    before = _stamp(note)
    result = subprocess.run(
        [_sh(), str(HOOK), *args],
        cwd=cwd,
        env=env,
        input=json.dumps({"hook_event_name": "Stop", "transcript": CHAT}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_S,
        check=False,
    )
    if wait and not args:
        _wait_for_note(note, before)
    return result


def _stamp(note: Path) -> int | None:
    try:
        return note.stat().st_mtime_ns if note.is_file() else None
    except OSError:
        return None


def _wait_for_note(note: Path, before: int | None) -> None:
    """The background writer replaces the note atomically (mv); wait until it has."""
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        stamp = _stamp(note)
        if stamp is not None and stamp != before:
            return
        time.sleep(0.05)
    raise AssertionError(f"the background writer did not write {note} in {TIMEOUT_S} s")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Branch'i 0042'ye bağlı, iki aktif spec'i, onaylı planı ve bir adım commit'i olan depo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "checkout", "-q", "-b", "feature/0042-demo")
    (repo / ".claude" / "hooks").mkdir(parents=True)
    shutil.copy2(HOOK, repo / ".claude" / "hooks" / "handoff-note.sh")
    shutil.copy2(TEMPLATE / ".gitignore", repo / ".claude" / ".gitignore")
    (repo / "specs" / "active").mkdir(parents=True)
    (repo / "specs" / "plans").mkdir(parents=True)
    (repo / "specs" / "active" / "0042-demo.md").write_text(
        "# Spec 0042\n\n- Status: In progress\n", encoding="utf-8"
    )
    (repo / "specs" / "active" / "0043-other.md").write_text(
        "# Spec 0043\n\n- Status: Draft\n", encoding="utf-8"
    )
    (repo / "specs" / "plans" / "0042-plan.md").write_text(PLAN, encoding="utf-8")
    (repo / "kaynak.txt").write_text("ilk\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "feat: one [plan 0042/1]")
    (repo / "kaynak.txt").write_text("değişti\n", encoding="utf-8")
    (repo / "yeni.txt").write_text("yeni\n", encoding="utf-8")
    return repo


def _note(repo: Path) -> str:
    return (repo / ".claude" / "handoff.local.md").read_text(encoding="utf-8")


def test_note_carries_every_field(repo: Path, tmp_path: Path) -> None:
    """AC-9 / Req. 7: date-time, branch, last commit, active specs, plan line, step, changes."""
    result = _hook(repo, cwd=tmp_path)

    assert result.returncode == 0
    note = _note(repo)
    sha = _git(repo, "rev-parse", "--short", "HEAD").strip()
    assert re.search(r"^- Written: \d{4}-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d{4}$", note, re.M), note
    assert "- Branch: feature/0042-demo\n" in note
    assert f"- HEAD: {sha} feat: one [plan 0042/1]\n" in note
    assert "- specs/active/0042-demo.md — Status: In progress\n" in note
    assert "- specs/active/0043-other.md — Status: Draft\n" in note
    assert "- Approved by / on: Test Kişi, 2026-11-07\n" in note
    assert "- First unfinished step: 2. İkinci adım.\n" in note
    assert " M kaynak.txt\n" in note
    assert "?? yeni.txt\n" in note


def test_note_holds_no_chat_and_writes_nothing_else(repo: Path, tmp_path: Path) -> None:
    """AC-9: the turn's data (stdin) never reaches the note; the hook prints nothing."""
    result = _hook(repo, cwd=tmp_path)

    assert result.returncode == 0
    assert CHAT not in _note(repo)
    assert result.stdout == "" and result.stderr == ""
    assert sorted(p.name for p in (repo / ".claude").iterdir()) == [
        ".gitignore",
        "handoff.local.md",
        "hooks",
    ]


def test_note_is_untracked(repo: Path, tmp_path: Path) -> None:
    """AC-9: git status does not show the note (.claude/.gitignore)."""
    before = _git(repo, "status", "--porcelain", "--untracked-files=all")

    assert _hook(repo, cwd=tmp_path).returncode == 0

    after = _git(repo, "status", "--porcelain", "--untracked-files=all")
    assert "handoff" not in after
    assert after == before


def test_note_is_refreshed_each_turn(repo: Path, tmp_path: Path) -> None:
    """AC-9: the next turn writes current values (a commit moves the step and HEAD on)."""
    assert _hook(repo, cwd=tmp_path).returncode == 0
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "feat: two [plan 0042/2]")

    assert _hook(repo, cwd=tmp_path).returncode == 0

    note = _note(repo)
    assert "- First unfinished step: 3. Üçüncü adım, kalın başlıksız.\n" in note
    assert "feat: two [plan 0042/2]" in note
    assert "- (clean)\n" in note


def test_every_step_committed(repo: Path, tmp_path: Path) -> None:
    for k in (2, 3):
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"feat: step [plan 0042/{k}]")

    assert _hook(repo, cwd=tmp_path).returncode == 0

    assert "- First unfinished step: (every step has its commit)\n" in _note(repo)


def test_branch_without_plan(repo: Path, tmp_path: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "main")

    assert _hook(repo, cwd=tmp_path).returncode == 0

    note = _note(repo)
    assert "- Branch: main\n" in note
    assert "- (no plan matches the branch number)\n" in note


@pytest.mark.parametrize("args", [(), ("--write",)], ids=["hook", "writer"])
def test_unwritable_note_never_fails_the_turn(
    repo: Path, tmp_path: Path, args: tuple[str, ...]
) -> None:
    """AC-9: when the note cannot be written, the hook still exits 0, silently, leaving nothing.

    The writer is run in the foreground too, so "leaving nothing" is checked after it finished.
    """
    (repo / ".claude" / "handoff.local.md").mkdir()

    result = _hook(repo, tmp_path, *args, wait=False)

    assert result.returncode == 0
    assert result.stdout == "" and result.stderr == ""
    if args:
        assert list((repo / ".claude" / "handoff.local.md").iterdir()) == []
        assert not list((repo / ".claude").glob("handoff.local.md.tmp.*"))


def test_writer_in_the_foreground_writes_the_same_note(repo: Path, tmp_path: Path) -> None:
    """The hook's background job is the script's own --write entry: same note, synchronously."""
    result = _hook(repo, tmp_path, "--write")

    assert result.returncode == 0
    assert result.stdout == "" and result.stderr == ""
    assert "- First unfinished step: 2. İkinci adım.\n" in _note(repo)


def test_hook_leaves_the_writing_to_a_background_job() -> None:
    """AC-9 / VERIFY F-1: the turn never waits for git; the 2 s cap can no longer cut the note.

    Structural, not wall-clock (Risk 3): the hook's last commands start the writer with &,
    then exit 0.
    """
    lines = [
        line.strip()
        for line in HOOK.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    tail = lines[lines.index('if [ "${1:-}" = --write ]; then') :]

    assert tail[-1] == "exit 0"
    assert any(line.endswith("&") and "--write" in line for line in tail), tail


@pytest.mark.parametrize("broken", ["no project dir", ".claude is a file"])
def test_missing_place_never_fails_the_turn(tmp_path: Path, broken: str) -> None:
    project = tmp_path / "project"
    if broken == ".claude is a file":
        project.mkdir()
        (project / ".claude").write_text("not a directory\n", encoding="utf-8")

    for args in [(), ("--write",)]:
        result = _hook(project, tmp_path, *args, wait=False)

        assert result.returncode == 0
        assert result.stdout == "" and result.stderr == ""


@pytest.mark.parametrize(
    "settings", [TEMPLATE / "settings.json", ROOT / ".claude" / "settings.json"]
)
def test_stop_hook_is_wired_with_two_second_cap(settings: Path) -> None:
    """AC-9: the hook runs at Stop and Claude Code cuts it off after 2 s at most."""
    stop = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["Stop"]
    commands = [h for entry in stop for h in entry["hooks"]]

    assert [h["command"] for h in commands] == [
        '"$CLAUDE_PROJECT_DIR"/.claude/hooks/handoff-note.sh'
    ]
    assert all(0 < h["timeout"] <= 2 for h in commands)


@pytest.mark.parametrize("relative", ["hooks/handoff-note.sh", ".gitignore", "settings.json"])
def test_template_and_installed_copy_agree(relative: str) -> None:
    """AC-9: the adapter template carries the same behavior as this repository's copy."""
    template = (TEMPLATE / relative).read_text(encoding="utf-8").replace("\r\n", "\n")
    installed = (ROOT / ".claude" / relative).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert template == installed


def test_init_claude_code_installs_the_hook(tmp_path: Path) -> None:
    """AC-9: every copy installed with ./scripts/init claude-code gets the hook and its ignore."""
    (tmp_path / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "init", tmp_path / "scripts" / "init")
    shutil.copytree(ROOT / "adapters", tmp_path / "adapters")

    result = subprocess.run(
        [_sh(), "scripts/init", "claude-code"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_S,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / ".claude" / "hooks" / "handoff-note.sh").read_bytes() == HOOK.read_bytes()
    assert (tmp_path / ".claude" / ".gitignore").read_bytes() == (
        TEMPLATE / ".gitignore"
    ).read_bytes()
