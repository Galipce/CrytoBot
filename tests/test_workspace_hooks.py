"""bug-001: settings.json'un doğrudan çağırdığı hook'lar git'te çalıştırılabilir (100755) kayıtlı.

Mod 100644 olursa POSIX'te hook "permission denied" (126) ile düşer, engelleme (exit 2) olmaz ve
specs/done/ değişmezliği (AGENTS.md kural 7) sessizce devre dışı kalır.
"""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = re.compile(r"\.claude/hooks/[\w.-]+")


def hook_scripts() -> list[str]:
    settings = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for groups in settings["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    ]
    return sorted({path for command in commands for path in HOOK_PATH.findall(command)})


def git_mode(path: str) -> str:
    out = subprocess.run(
        ["git", "ls-files", "-s", "--", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout
    return out.split(" ", 1)[0]


def test_hooks_called_by_settings_are_executable_in_git() -> None:
    scripts = hook_scripts()

    assert scripts, "settings.json hiçbir .claude/hooks betiği çağırmıyor"
    assert {path: git_mode(path) for path in scripts} == dict.fromkeys(scripts, "100755")
