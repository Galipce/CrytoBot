"""AC-8: hassas modüllerin her birinde test edilmemiş dallı kod coverage kapısını kırmızı yapar."""

import pytest

from tests.tooling.conftest import SENSITIVE_MODULES, Project

pytestmark = pytest.mark.slow

UNTESTED_BRANCHES = '''"""Bilerek eksik test edilen dallı kod."""


def classify(x: int) -> str:
    if x > 0:
        return "positive"
    if x < 0:
        return "negative"
    return "zero"
'''


def fully_tested_bulk(count: int) -> str:
    return '"""Tam test edilen, eşiği toplamda yükseltecek kadar uzun kod."""\n\n' + "".join(
        f"def f{i}(x: int) -> int:\n    if x > {i}:\n        return x\n    return {i}\n\n\n"
        for i in range(count)
    )


def source_lines(project: Project, module: str) -> int:
    return sum(
        len(path.read_text(encoding="utf-8").splitlines())
        for path in (project.root / "src" / "crytobot" / module).glob("*.py")
    )


def untested_code(project: Project, module: str) -> str:
    """UNTESTED_BRANCHES plus one never-called function per source line already in the module.

    Each adds three unexecuted statements, so the module drops under 90% however much
    well-tested code it already has (plan 0002, amendment A-1).
    """
    return UNTESTED_BRANCHES + "".join(
        f"\n\ndef g{i}(x: int) -> int:\n    if x > {i}:\n        return x\n    return {i}\n"
        for i in range(source_lines(project, module))
    )


def partial_test(module: str) -> str:
    # all gated modules are imported (as tests/test_module_layout.py does), so the gate fails on
    # the missing branch, not on "No data to report" for a module no test touched
    return (
        "import crytobot.execution\n"
        "import crytobot.persistence\n"
        "import crytobot.portfolio\n"
        "import crytobot.risk\n"
        f"from crytobot.{module}._logic import classify\n\n\n"
        "def test_positive_only() -> None:\n"
        '    assert classify(1) == "positive"\n'
    )


@pytest.mark.parametrize("module", SENSITIVE_MODULES)
def test_untested_branch_in_sensitive_module_red(project: Project, module: str) -> None:
    project.write(f"src/crytobot/{module}/_logic.py", untested_code(project, module))
    project.write("tests/test_logic.py", partial_test(module))

    tests = project.run_step("test-unit")
    gate = project.run_step("coverage")

    assert tests.returncode == 0, tests.stdout + tests.stderr
    assert gate.returncode != 0
    assert module in gate.stdout and "_logic.py" in gate.stdout
    assert "fail-under" in gate.stdout + gate.stderr


def test_well_tested_module_does_not_hide_untested_one(project: Project) -> None:
    """Toplam %90'ı geçse bile execution'daki eksik test kapıyı kırmızı yapar (VERIFY F-1)."""
    # an untested function misses 5 of its 6 statements and branches, a bulk one covers all 6:
    # eight bulk functions per untested one keep the total over 90% (plan 0006, amendment A-1)
    count = 8 * source_lines(project, "execution") + 40
    untested = untested_code(project, "execution")
    project.write("src/crytobot/risk/_bulk.py", fully_tested_bulk(count))
    project.write(
        "tests/test_bulk.py",
        "from crytobot.risk import _bulk\n\n\n"
        "def test_bulk() -> None:\n"
        f"    for i in range({count}):\n"
        "        f = getattr(_bulk, f'f{i}')\n"
        "        assert f(i + 1) == i + 1\n"
        "        assert f(i) == i\n",
    )
    project.write("src/crytobot/execution/_logic.py", untested)
    project.write("tests/test_logic.py", partial_test("execution"))

    tests = project.run_step("test-unit")
    total = project.run("coverage report")
    gate = project.run_step("coverage")

    assert tests.returncode == 0, tests.stdout + tests.stderr
    # precondition: the three-module total clears 90%, so only a per-module gate can catch this
    assert total.returncode == 0, total.stdout + total.stderr
    assert gate.returncode != 0
    assert "execution" in gate.stdout and "fail-under" in gate.stdout + gate.stderr


def test_clean_skeleton_passes_gate(project: Project) -> None:
    project.write(
        "tests/test_imports.py",
        "import crytobot.risk, crytobot.execution, crytobot.portfolio, crytobot.persistence\n",
    )

    tests = project.run_step("test-unit")
    gate = project.run_step("coverage")

    assert tests.returncode == 0, tests.stdout + tests.stderr
    assert gate.returncode == 0, gate.stdout + gate.stderr
