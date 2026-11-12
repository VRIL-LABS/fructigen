"""The package imports the standard library and itself, and nothing else.

This is the dependency rule in CONSTRAINTS.md, checked from the source rather than from what happens
to be installed: a consumer installed in the same environment would otherwise import fine and hide
the violation.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "fructigen"


def imported_roots(source: str) -> set[str]:
    """Top-level names of every absolute import in ``source``. Relative imports are the package's
    own modules and are skipped."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_scanner_sees_absolute_imports_and_skips_relative_ones():
    source = "import json\nimport vril_bench.bench\nfrom requests import get\nfrom .plan import Call\n"
    assert imported_roots(source) == {"json", "vril_bench", "requests"}


def test_the_package_imports_only_the_standard_library_and_itself():
    allowed = set(sys.stdlib_module_names) | {"fructigen"}
    modules = sorted(PACKAGE.rglob("*.py"))
    assert modules, "no package source found; the check would pass vacuously"
    offenders = {str(path.relative_to(PACKAGE)): sorted(imported_roots(path.read_text("utf-8")) - allowed)
                 for path in modules}
    assert {name: roots for name, roots in offenders.items() if roots} == {}
