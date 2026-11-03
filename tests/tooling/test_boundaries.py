"""AC-5: her R-3 kuralı bilerek ihlal edilince sınır adımı kırmızı olur ve kuralı adlandırır."""

import pytest

from tests.tooling.conftest import Project, check_step

pytestmark = pytest.mark.slow

VIOLATIONS = {
    "R-3a": {"src/crytobot/strategy/_probe.py": "import crytobot.execution\n"},
    "R-3b": {"src/crytobot/portfolio/_probe.py": "import crytobot.execution\n"},
    "R-3c": {"src/crytobot/analysis/_probe.py": "import crytobot.portfolio\n"},
    "R-3e": {"src/crytobot/portfolio/_probe.py": "import crytobot.persistence\n"},
    "R-3d": {
        "src/crytobot/risk/limits.py": '"""Risk modülünün iç alt modülü."""\n',
        "src/crytobot/reporting/_probe.py": "from crytobot.risk import limits\n",
    },
}


@pytest.mark.parametrize("rule", sorted(VIOLATIONS))
def test_violation_names_contract(project: Project, rule: str) -> None:
    for path, content in VIOLATIONS[rule].items():
        project.write(path, content)

    result = project.run_step("boundaries")

    assert result.returncode != 0
    broken = [line for line in result.stdout.splitlines() if line.endswith(" BROKEN")]
    assert [line.split(":", 1)[0] for line in broken] == (
        ["R-3a", "R-3b"] if rule == "R-3a" else [rule]
    )


def test_clean_tree_passes(project: Project) -> None:
    result = project.run_step("boundaries")

    assert result.returncode == 0, result.stdout
    assert "5 kept, 0 broken" in result.stdout


def test_module_importing_its_own_submodule_passes(project: Project) -> None:
    """R-3d yalnızca başka modülün içini yasaklar; modül kendi alt modüllerini import edebilir."""
    project.write("src/crytobot/risk/_b.py", '"""Risk modülünün iç alt modülü."""\n')
    project.write("src/crytobot/risk/_a.py", "from crytobot.risk import _b\n")

    result = project.run_step("boundaries")

    assert result.returncode == 0, result.stdout


def test_root_package_importing_module_internals_is_violation(project: Project) -> None:
    """Kök paket hiçbir modülün sahibi değildir; bir modülün içine erişmesi de R-3d ihlalidir."""
    project.write("src/crytobot/risk/limits.py", '"""Risk modülünün iç alt modülü."""\n')
    project.write("src/crytobot/__init__.py", "from crytobot.risk import limits\n")

    result = project.run_step("boundaries")

    assert result.returncode != 0
    assert "R-3d: no module imports another module's internal submodules BROKEN" in result.stdout


def write_legitimate_flow(project: Project) -> None:
    """strategy → risk → execution: risk kökü kendi _flow'unu, o da execution'ı import eder."""
    project.write("src/crytobot/risk/_flow.py", "import crytobot.execution\n")
    project.write(
        "src/crytobot/risk/__init__.py",
        '"""Risk."""\n\nfrom crytobot.risk import _flow as _flow\n\n__all__: list[str] = []\n',
    )
    project.write("src/crytobot/strategy/_flow.py", "import crytobot.risk\n")


def test_allowed_flow_strategy_risk_execution_passes(project: Project) -> None:
    """Meşru akış dolaylı import yüzünden kırmızı olmamalı (yasaklar yalnız doğrudan importlar)."""
    write_legitimate_flow(project)

    result = project.run_step("boundaries")

    assert result.returncode == 0, result.stdout


def test_same_flow_is_red_when_indirect_imports_are_forbidden(project: Project) -> None:
    """Kontrol: zincir gerçekten var; dolaylı importlar yasaklanınca R-3a/R-3b bozulur."""
    write_legitimate_flow(project)
    pyproject = project.root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(
        text.replace("allow_indirect_imports = true", "allow_indirect_imports = false"),
        encoding="utf-8",
    )

    result = project.run_step("boundaries")

    broken = [line.split(":", 1)[0] for line in result.stdout.splitlines() if "BROKEN" in line]
    assert result.returncode != 0
    assert {"R-3a", "R-3b"} <= set(broken)


def test_clean_tree_passes_with_output_discarded(project: Project) -> None:
    """B-7: çıktısı atılan (`>/dev/null`) sınır adımı da yeşil; Windows CI ile aynı sonucu verir."""
    result = project.run(check_step("boundaries") + " >/dev/null 2>&1")

    assert result.returncode == 0
