"""AC-3: slow test yokken full yeşil; başarısız slow test full'ü kırmızı yapar, fast çalıştırmaz."""

import pytest

from tests.tooling.conftest import Project

pytestmark = pytest.mark.slow

FAILING_SLOW_TEST = """import pytest


@pytest.mark.slow
def test_fails_on_purpose() -> None:
    assert False
"""


def test_slow_step_green_without_slow_tests(project: Project) -> None:
    result = project.run_step("test-slow")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "deselected" in result.stdout


def test_failing_slow_test_red_in_full_skipped_in_fast(project: Project) -> None:
    project.write("tests/test_slow_fail.py", FAILING_SLOW_TEST)

    fast = project.run_step("test-unit")
    full = project.run_step("test-slow")

    assert fast.returncode == 0, fast.stdout + fast.stderr
    assert "1 deselected" in fast.stdout
    assert full.returncode == 1
    assert "test_fails_on_purpose" in full.stdout
