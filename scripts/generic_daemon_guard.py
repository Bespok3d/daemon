"""Guard: generic `core/` code reaches the jinni only through the seam, never device code.

The daemon is generic (ADR-0037): it orchestrates and never names a device or printer service. The
device half is the jinni, behind one door, `core/jinni_client`. So a `core/` file may import that
door and the shared contract shapes (`jinni.contracts`, the serializable values that cross the
boundary), but nothing else under `jinni`: not the loader, not a tier, not the loopback probes. This
catches the coupling mechanically, the in-process equivalent of a process boundary's enforcement.

Only the seam itself is exempt; it is the door and imports the jinni internals on the daemon's
behalf. Production `core/` code only: tests are white-box and may reach in on purpose.
"""
import ast
import sys
from pathlib import Path

SOURCE_ROOT = "core"
CONTRACT_MODULE = "jinni.contracts"


def is_seam_path(path: Path) -> bool:
    """The one door allowed to import the jinni internals (a module `core/jinni_client.py` or a
    package `core/jinni_client/`); every other `core/` file goes through it."""
    return path.stem == "jinni_client" or "jinni_client" in path.parts


def _reaches_jinni(module: str | None) -> bool:
    return module == "jinni" or (module is not None and module.startswith("jinni."))


def device_imports(path: Path) -> list[tuple[int, str]]:
    """Imports in one file that reach the jinni outside the shared contract shapes."""
    tree = ast.parse(path.read_text(), str(path))
    return [
        (lineno, statement)
        for node in ast.walk(tree)
        for lineno, module, statement in _import_targets(node)
        if _reaches_jinni(module) and module != CONTRACT_MODULE
    ]


def _import_targets(node: ast.AST) -> list[tuple[int, str | None, str]]:
    if isinstance(node, ast.ImportFrom) and node.level == 0:
        names = ", ".join(alias.name for alias in node.names)
        return [(node.lineno, node.module, f"from {node.module} import {names}")]
    if isinstance(node, ast.Import):
        return [(node.lineno, alias.name, f"import {alias.name}") for alias in node.names]
    return []


def main() -> int:
    violations = [
        (path, lineno, statement)
        for path in sorted(Path(SOURCE_ROOT).rglob("*.py"))
        if not is_seam_path(path)
        for lineno, statement in device_imports(path)
    ]
    for path, lineno, statement in violations:
        print(f"{path}:{lineno}: core reaches the jinni outside the seam: {statement}")
    if violations:
        print(f"\n{len(violations)} device coupling(s) in core/: route via core.jinni_client.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
