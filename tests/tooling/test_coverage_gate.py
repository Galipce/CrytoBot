"""AC-8: hassas modüllerde test edilmemiş dallı kod coverage kapısını kırmızı yapar."""

import pytest

from tests.tooling.conftest import Project

pytestmark = pytest.mark.slow

UNTESTED_BRANCHES = '''"""Bilerek eksik test edilen dallı kod."""


def classify(x: int) -> str:
    if x > 0:
        return "positive"
    if x < 0:
        return "negative"
    return "zero"
'''

PARTIAL_TEST = """from crytobot.risk._logic import classify


def test_positive_only() -> None:
    assert classify(1) == "positive"
"""


def test_untested_branch_in_sensitive_module_red(project: Project) -> None:
    project.write("src/crytobot/risk/_logic.py", UNTESTED_BRANCHES)
    project.write("tests/test_logic.py", PARTIAL_TEST)

    tests = project.run_step("test-unit")
    gate = project.run_step("coverage")

    assert tests.returncode == 0, tests.stdout + tests.stderr
    assert gate.returncode != 0
    assert "risk" in gate.stdout and "_logic.py" in gate.stdout
    assert "fail-under" in gate.stdout + gate.stderr


def test_clean_skeleton_passes_gate(project: Project) -> None:
    project.write(
        "tests/test_imports.py", "import crytobot.risk, crytobot.execution, crytobot.portfolio\n"
    )

    tests = project.run_step("test-unit")
    gate = project.run_step("coverage")

    assert tests.returncode == 0, tests.stdout + tests.stderr
    assert gate.returncode == 0, gate.stdout + gate.stderr
