"""AC-6: lint ihlali, format bozukluğu ve tip hatası check'i ilgili adımda kırmızı yapar."""

import pytest

from tests.tooling.conftest import Project

pytestmark = pytest.mark.slow


def test_clean_copy_passes_lint_format_types(project: Project) -> None:
    for step in ("lint", "format", "types"):
        result = project.run_step(step)
        assert result.returncode == 0, f"{step}: {result.stdout}{result.stderr}"


def test_lint_violation_red(project: Project) -> None:
    project.write("src/crytobot/risk/_bad.py", "import os\n")

    result = project.run_step("lint")

    assert result.returncode != 0
    assert "F401" in result.stdout


def test_format_violation_red(project: Project) -> None:
    project.write("src/crytobot/risk/_bad.py", "x  =  1\n")

    result = project.run_step("format")

    assert result.returncode != 0
    assert "_bad.py" in result.stdout + result.stderr


def test_type_error_red(project: Project) -> None:
    project.write("src/crytobot/risk/_bad.py", 'x: int = "not an int"\n')

    result = project.run_step("types")

    assert result.returncode != 0
    assert "Incompatible types in assignment" in result.stdout
