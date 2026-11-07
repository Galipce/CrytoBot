"""Spec 0027: Antigravity adaptörü — kurulum (AC-1), komut eşliği (AC-2, AC-3), ince gövde (AC-4).

Betikler deponun geçici bir kopyasında (depo dışında) gerçek çıktı ve çıkış koduyla sınanır.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]
ANTIGRAVITY = ROOT / "adapters" / "antigravity" / "skills"
CODEX = ROOT / "adapters" / "codex" / "skills"
COMMANDS = sorted(
    p.stem for p in (ROOT / "adapters" / "claude-code" / ".claude" / "commands").glob("*.md")
)
# A-1: Antigravity's built-in /plan shadows a skill named plan, so PLAN is /anew-plan there.
RENAMED = {"plan": "anew-plan"}
SKILLS = sorted(RENAMED.get(c, c) for c in COMMANDS)
TIMEOUT_S = 120


def _call_form(text: str) -> str:
    """Codex call form → Antigravity call form: $name → /name, $plan → /anew-plan."""
    return re.sub(r"\$([a-z][a-z-]*)", lambda m: "/" + RENAMED.get(m[1], m[1]), text)


def _sh(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    sh = shutil.which("sh")
    assert sh, "sh is required (Git Bash on Windows)"
    return subprocess.run(
        [sh, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_S,
        check=False,
    )


def _body(path: Path) -> str:
    """SKILL.md'nin ön bilgi (front matter) sonrası metni, satır sonları LF."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    parts = text.split("---\n", 2)
    assert len(parts) == 3 and parts[0] == "", f"{path} has no front matter"
    return parts[2]


def _description(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.search(r"^description: (.*)$", text, re.MULTILINE)
    assert match, f"{path} has no description"
    return match[1]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Boş bir kopya: yalnızca scripts/init ve adapters/."""
    (tmp_path / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "init", tmp_path / "scripts" / "init")
    shutil.copytree(ROOT / "adapters", tmp_path / "adapters")
    return tmp_path


def test_commands_exist() -> None:
    """Twelve commands: the Claude Code list is the reference, and none is missing."""
    assert len(COMMANDS) == 12
    assert sorted(p.name for p in ANTIGRAVITY.iterdir() if p.is_dir()) == SKILLS


def test_plan_is_anew_plan_everywhere() -> None:
    """A-1: no skill is named plan, and no skill points at the built-in /plan."""
    assert not (ANTIGRAVITY / "plan").exists()
    for name in SKILLS:
        text = (ANTIGRAVITY / name / "SKILL.md").read_text(encoding="utf-8")
        assert re.search(rf"^name: {re.escape(name)}\r?$", text, re.MULTILINE), name
        assert not re.search(r"/plan\b", text), name


def test_init_installs_every_command(workspace: Path) -> None:
    """AC-1: an empty copy gets one .agents/skills/<name>/SKILL.md per command."""
    result = _sh(workspace, "scripts/init", "antigravity")

    assert result.returncode == 0, result.stdout + result.stderr
    for name in SKILLS:
        installed = workspace / ".agents" / "skills" / name / "SKILL.md"
        assert installed.read_bytes() == (ANTIGRAVITY / name / "SKILL.md").read_bytes()


def test_second_run_keeps_every_file(workspace: Path) -> None:
    """AC-1: the second run changes nothing and reports each file as kept."""
    assert _sh(workspace, "scripts/init", "antigravity").returncode == 0
    skills = workspace / ".agents" / "skills"
    for name in SKILLS:
        (skills / name / "SKILL.md").write_text(f"customized {name}\n", encoding="utf-8")

    result = _sh(workspace, "scripts/init", "antigravity")

    assert result.returncode == 0, result.stdout + result.stderr
    for name in SKILLS:
        assert (skills / name / "SKILL.md").read_text(encoding="utf-8") == f"customized {name}\n"
        assert f"kept   .agents/skills/{name}/SKILL.md (exists" in result.stdout


def test_force_overwrites(workspace: Path) -> None:
    """AC-1: --force overwrites an existing file."""
    assert _sh(workspace, "scripts/init", "antigravity").returncode == 0
    target = workspace / ".agents" / "skills" / "anew-plan" / "SKILL.md"
    target.write_text("customized\n", encoding="utf-8")

    result = _sh(workspace, "scripts/init", "--force", "antigravity")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "kept" not in result.stdout
    assert target.read_bytes() == (ANTIGRAVITY / "anew-plan" / "SKILL.md").read_bytes()


def test_help_lists_antigravity(workspace: Path) -> None:
    """AC-1: the help text names the antigravity adapter."""
    result = _sh(workspace, "scripts/init", "--help")

    assert re.search(r"^  antigravity +\.agents/skills/", result.stdout, re.MULTILINE), (
        result.stdout
    )


@pytest.mark.parametrize("name", COMMANDS)
def test_body_is_the_codex_pointer(name: str) -> None:
    """AC-4: the body equals the Codex skill's, except call form ($name → /name) and tool name."""
    expected = _call_form(_body(CODEX / name / "SKILL.md")).replace("Codex", "Antigravity")

    assert _body(ANTIGRAVITY / RENAMED.get(name, name) / "SKILL.md") == expected


@pytest.mark.parametrize("name", SKILLS)
def test_description_says_explicit_only(name: str) -> None:
    """AC-3: every description says the command runs only on an explicit /name."""
    assert f"Run only when the user types /{name} explicitly." in _description(
        ANTIGRAVITY / name / "SKILL.md"
    )


@pytest.mark.parametrize("name", SKILLS)
def test_installed_copy_matches_template(name: str) -> None:
    """This repository's installed copy is the template's (init antigravity, plan 0027 step 1)."""
    installed = ROOT / ".agents" / "skills" / name / "SKILL.md"
    assert _body(installed) == _body(ANTIGRAVITY / name / "SKILL.md")
    assert _description(installed) == _description(ANTIGRAVITY / name / "SKILL.md")


@pytest.fixture
def core(tmp_path: Path) -> Path:
    """Doctor'ın okuduğu çekirdek; projenin spec ve planları olmadan (selftest gibi)."""
    for name in ("AGENTS.md", "README.md", ".anew-version"):
        shutil.copy2(ROOT / name, tmp_path / name)
    for name in ("docs", "workflows", "prompts", "scripts", "adapters"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    for path in (ROOT / "specs").rglob("*.md"):
        relative = path.relative_to(ROOT)
        if path.name.startswith("TEMPLATE") or path.name == "README.md":
            (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, tmp_path / relative)
    return tmp_path


def _doctor(cwd: Path) -> subprocess.CompletedProcess[str]:
    return _sh(
        cwd, "-c", "unset ANEW_BASE_REF GITHUB_BASE_REF GITHUB_EVENT_PATH; exec sh scripts/doctor"
    )


def test_doctor_clean_parity_names_antigravity(core: Path) -> None:
    """AC-2: with every skill present, parity is clean and Antigravity is named."""
    result = _doctor(core)

    assert (
        "ok    adapter parity: every Claude Code command exists for Cursor, Copilot, "
        "Codex and Antigravity" in result.stdout
    )
    assert "antigravity" not in "\n".join(
        line for line in result.stdout.splitlines() if line.startswith("FAIL")
    )


def test_doctor_fails_on_each_missing_command(core: Path) -> None:
    """AC-2: every removed Antigravity command fails doctor, each by its name."""
    for name in SKILLS:
        shutil.rmtree(core / "adapters" / "antigravity" / "skills" / name)

    result = _doctor(core)

    assert result.returncode == 1
    for name in SKILLS:
        assert f"FAIL  adapter parity: {name} missing in antigravity" in result.stdout


def test_doctor_fails_on_each_missing_explicit_only_phrase(core: Path) -> None:
    """AC-3: every description without the explicit-only phrase fails doctor, each by its name."""
    for name in SKILLS:
        skill = core / "adapters" / "antigravity" / "skills" / name / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        phrase = f" Run only when the user types /{name} explicitly."
        assert phrase in text
        skill.write_text(text.replace(phrase, ""), encoding="utf-8")

    result = _doctor(core)

    assert result.returncode == 1
    for name in SKILLS:
        assert (
            f"FAIL  adapter parity: antigravity skill {name} is not explicit-only" in result.stdout
        )


def test_doctor_ignores_phrase_outside_description(core: Path) -> None:
    """AC-3: the phrase counts only in the description, not anywhere in the body."""
    skill = core / "adapters" / "antigravity" / "skills" / "anew-plan" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    phrase = " Run only when the user types /anew-plan explicitly."
    skill.write_text(text.replace(phrase, "") + phrase.strip() + "\n", encoding="utf-8")

    result = _doctor(core)

    assert "FAIL  adapter parity: antigravity skill anew-plan is not explicit-only" in result.stdout


SIGNATURE = "Co-Authored-By: Gemini (Antigravity) <noreply@google.com>"


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8").replace("\r\n", "\n")


def test_gemini_signature_lives_in_git_md_only() -> None:
    """AC-11: docs/git.md defines the signature; the adapter points at it and never copies it."""
    assert f"`{SIGNATURE}`" in _text("docs/git.md")
    readme = _text("adapters/antigravity/README.md")
    assert "`docs/git.md` (Commits)" in readme
    assert "Co-Authored-By" not in readme
    for name in SKILLS:
        assert "Co-Authored-By" not in _text(f"adapters/antigravity/skills/{name}/SKILL.md")


@pytest.mark.parametrize("relative", ["README.md", "adapters/README.md", "docs/commands.md"])
def test_tool_lists_name_antigravity(relative: str) -> None:
    """AC-12: the tool lists name Antigravity next to the other tools."""
    text = _text(relative)
    assert re.search(r"Codex,? and Antigravity|Codex, Antigravity|`antigravity/?`", text), relative


def test_rule_table_has_antigravity_column() -> None:
    """AC-12: README's rule table has a column for Antigravity in every row."""
    rows = [line for line in _text("README.md").splitlines() if line.startswith("| Rule |")]
    assert rows == [
        "| Rule | Claude Code | GitHub Copilot | Cursor | Codex | Antigravity | Other tools |"
    ]


def test_adapter_readme_covers_switch_gap_and_sharing() -> None:
    """AC-12: manual switch flow, explicit-only gap, sharing the folder with Codex."""
    readme = _text("adapters/antigravity/README.md")
    for heading in (
        "## The explicit-only gap",
        "## Sharing `.agents/skills/` with Codex",
        "## Resuming Claude's work in Gemini (manual switch)",
    ):
        assert heading in readme
    assert r"scripts\gemini-devam.ps1" in readme
    assert ".claude/handoff.local.md" in readme


def test_changelog_records_the_work() -> None:
    """AC-12: CHANGELOG has an entry above the ANEW versions."""
    text = _text("CHANGELOG.md")
    unreleased = text.index("## Unreleased — CrytoBot (yerel)")
    assert unreleased < text.index("## How to upgrade") < text.index("## v")
    entry = text[unreleased : text.index("## How to upgrade")]
    for needed in ("Antigravity", "scripts/gemini-devam.ps1", "handoff.local.md", "docs/git.md"):
        assert needed in entry
