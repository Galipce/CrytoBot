"""import-linter özel sözleşme tipi: başka bir modülün iç alt modülüne doğrudan import yok.

Kural (docs/architecture.md, Forbidden dependencies; spec 0001 R-3): bir modüle dışarıdan yalnızca
kökü (``crytobot.risk``) üzerinden erişilir; ``crytobot.risk.<herhangi>`` o modülün içidir.
Yalnızca doğrudan importlar denetlenir; bir modülün kendi alt modüllerini import etmesi serbesttir.
"""

from grimp import ImportGraph
from importlinter import Contract, ContractCheck, fields, output


def _owner(module: str, root: str) -> str | None:
    """``crytobot.risk.limits`` → ``crytobot.risk``; kök paketin kendisi için None."""
    parts = module.split(".")
    root_depth = root.count(".") + 1
    return ".".join(parts[: root_depth + 1]) if len(parts) > root_depth else None


class NoForeignSubmoduleImportsContract(Contract):
    """Configuration options:
    - root_package: modülleri doğrudan çocukları olan uygulama paketi (ör. ``crytobot``).
    """

    type_name = "no_foreign_submodule_imports"

    root_package = fields.StringField()

    def check(self, graph: ImportGraph, verbose: bool) -> ContractCheck:
        root = str(self.root_package)
        violations: list[dict[str, object]] = []
        for importer in sorted(graph.modules):
            if importer != root and not importer.startswith(root + "."):
                continue
            importer_owner = _owner(importer, root)
            for imported in sorted(graph.find_modules_directly_imported_by(importer)):
                if not imported.startswith(root + "."):
                    continue
                imported_owner = _owner(imported, root)
                is_internal = imported != imported_owner
                if is_internal and imported_owner != importer_owner:
                    lines = [
                        d["line_number"]
                        for d in graph.get_import_details(importer=importer, imported=imported)
                    ]
                    violations.append({"importer": importer, "imported": imported, "lines": lines})
        return ContractCheck(kept=not violations, metadata={"violations": violations})

    def render_broken_contract(self, check: ContractCheck) -> None:
        for v in check.metadata["violations"]:
            output.print_error(
                f"{v['importer']} -> {v['imported']} (l.{v['lines']}): "
                "import the module root, not its internals",
                bold=False,
            )
            output.new_line()
