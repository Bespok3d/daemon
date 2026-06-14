"""Guard: a name imported across files is public, so it must not start with `_`.

The `_` prefix means "private to the file that defines it". When one module imports a `_name` from
another (a relative import inside this package), that name is part of the other module's public
interface and the `_` is a lie. This catches the smell mechanically so it cannot accumulate into a
cleanup pass.

`from x import name as _alias` is fine: the imported name is public; the `_alias` is a local
binding private to the importing file. Only `from x import _name` (a file's private) is flagged.

Production code only: tests are white-box and may reach into a module's internals on purpose.
"""
import ast
import sys
from pathlib import Path

SOURCE_ROOTS = ("core", "api", "jinni")


def _private_imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(), str(path))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level == 0:
            continue
        module = node.module or "."
        for alias in node.names:
            name = alias.name
            if alias.asname is None and name.startswith("_") and not name.startswith("__"):
                offenders.append((node.lineno, f"from {'.' * node.level}{module} import {name}"))
    return offenders


def main() -> int:
    violations = [
        (path, lineno, statement)
        for root in SOURCE_ROOTS
        for path in sorted(Path(root).rglob("*.py"))
        for lineno, statement in _private_imports(path)
    ]
    for path, lineno, statement in violations:
        print(f"{path}:{lineno}: imports a private name across files: {statement}")
    if violations:
        print(f"\n{len(violations)} cross-file private import(s): rename the source public.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
