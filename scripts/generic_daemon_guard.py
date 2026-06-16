"""Guard: the daemon and the jinni share ONLY the protocol; no `core/` code imports the jinni
runtime, and the shared protocol contract carries only generic shapes, never device vocabulary.

The daemon is generic (ADR-0037): it orchestrates and never names a device or printer service. The
device half is the jinni runtime, which lives outside the daemon repo and is reached at runtime over
the socket. The only thing the two sides share is the `protocol` package (defined here, imported by
the jinni). So no `core/` file imports `jinni.*` at all: not the loader, not a tier, not the probes.
The in-process transport injects its jinni (a test sets `jinni_client.get_jinni`) rather than
importing it. This catches the coupling mechanically, the way a process boundary would.

The protocol contract (`protocol/contracts.py`) is the one module the daemon and the jinni both
import, so it must hold only generic data SHAPES (the dataclasses that cross the wire). A
module-level string constant there is device vocabulary, a service name or an action token, which is
the jinni's. Naming one in the contract is the same coupling read from the other side.

Production `core/` code only: tests are white-box and may reach in on purpose.
"""
import ast
import sys
from pathlib import Path

SOURCE_ROOT = "core"
CONTRACT_PATH = Path("protocol/contracts.py")


def _reaches_jinni(module: str | None) -> bool:
    return module == "jinni" or (module is not None and module.startswith("jinni."))


def device_imports(path: Path) -> list[tuple[int, str]]:
    """Imports in one file that reach the jinni runtime (anything under `jinni`)."""
    tree = ast.parse(path.read_text(), str(path))
    return [
        (lineno, statement)
        for node in ast.walk(tree)
        for lineno, module, statement in _import_targets(node)
        if _reaches_jinni(module)
    ]


def _import_targets(node: ast.AST) -> list[tuple[int, str | None, str]]:
    if isinstance(node, ast.ImportFrom) and node.level == 0:
        names = ", ".join(alias.name for alias in node.names)
        return [(node.lineno, node.module, f"from {node.module} import {names}")]
    if isinstance(node, ast.Import):
        return [(node.lineno, alias.name, f"import {alias.name}") for alias in node.names]
    return []


def _assigned_string_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):  # noqa: E501
        return [target.id for target in node.targets if isinstance(target, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):  # noqa: E501
        return [node.target.id]
    return []


def contract_vocabulary(path: Path) -> list[tuple[int, str]]:
    """Module-level string constants in the protocol contract. The contract is generic data shapes
    the daemon and jinni both import; a string constant there is device vocabulary (a service name,
    an action token), which the jinni owns."""
    if not path.exists():
        return []
    tree = ast.parse(path.read_text(), str(path))
    return [
        (node.lineno, name)
        for node in tree.body
        for name in _assigned_string_names(node)
    ]


def main() -> int:
    violations = [
        (path, lineno, statement)
        for path in sorted(Path(SOURCE_ROOT).rglob("*.py"))
        for lineno, statement in device_imports(path)
    ]
    vocabulary = contract_vocabulary(CONTRACT_PATH)
    for path, lineno, statement in violations:
        print(f"{path}:{lineno}: core imports the jinni runtime; only the protocol crosses: {statement}")  # noqa: E501
    for lineno, name in vocabulary:
        print(f"{CONTRACT_PATH}:{lineno}: the protocol contract names device vocabulary: {name}; move it to the jinni")  # noqa: E501
    if violations:
        print(f"\n{len(violations)} jinni-runtime import(s) in core/: talk to the jinni over the protocol.")  # noqa: E501
    if vocabulary:
        print(f"\n{len(vocabulary)} device constant(s) in the protocol contract: move them to the jinni.")  # noqa: E501
    return 1 if violations or vocabulary else 0


if __name__ == "__main__":
    sys.exit(main())
