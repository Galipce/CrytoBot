"""Spec 0051 AC-7 (plan step 1): alt süreç başlatan tek modül `llm`'dir; `llm` hiçbir proje
modülünü import etmez (R-3j'nin yanında, dolaylı yazımları da yakalayan AST denetimi)."""

import ast
from pathlib import Path

import crytobot

PACKAGE = Path(crytobot.__file__).parent
SPAWNERS = ("subprocess", "multiprocessing", "pty")
SPAWN_CALLS = ("system", "popen", "spawnl", "spawnv", "execv", "execl", "startfile", "posix_spawn")


def imported(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def os_spawn_calls(tree: ast.AST) -> set[str]:
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
        and node.attr.startswith(SPAWN_CALLS)
    }


def test_only_llm_imports_subprocess() -> None:
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(PACKAGE).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        spawns = {name for name in imported(tree) if name.split(".")[0] in SPAWNERS}
        if (spawns or os_spawn_calls(tree)) and not relative.startswith("llm/"):
            offenders.append(relative)
    assert offenders == []


def test_llm_imports_no_project_module() -> None:
    for path in sorted((PACKAGE / "llm").rglob("*.py")):
        names = imported(ast.parse(path.read_text(encoding="utf-8")))
        project = {name for name in names if name.startswith("crytobot")}
        assert project <= {"crytobot.llm", "crytobot.llm._claude", "crytobot.llm._workdir"}, path
