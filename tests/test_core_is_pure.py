"""The core must stay plain Python: no Home Assistant imports."""

import ast
from pathlib import Path

CORE = Path(__file__).parent.parent / "custom_components/spot_heating_planner/core"


def imported_modules(path: Path) -> set[str]:
    """Top-level names of every module a file imports."""
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_core_does_not_import_home_assistant() -> None:
    files = sorted(CORE.glob("*.py"))
    assert files
    for path in files:
        assert "homeassistant" not in imported_modules(path), path.name
