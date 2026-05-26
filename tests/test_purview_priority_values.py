"""
Regression guard for LEM-611: priority= keyword arguments in new_recommendation()
calls within Recommendations/purview/ must be valid values accepted by new_recommendation().

The bug: four files hardcoded priority="Critical", which new_recommendation() rejects
with ValueError. A single failure propagated through asyncio.gather (without
return_exceptions=True) wiped out all Purview recommendations silently.
"""
import ast
from pathlib import Path

PURVIEW_DIR = Path(__file__).parent.parent / "Recommendations" / "purview"
VALID_PRIORITIES = {"High", "Medium", "Low", ""}


def _invalid_priority_literals(filepath: Path) -> list[tuple[int, str]]:
    """Return (lineno, value) for priority= args in new_recommendation() that are invalid."""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_new_rec = (
            (isinstance(func, ast.Name) and func.id == "new_recommendation")
            or (isinstance(func, ast.Attribute) and func.attr == "new_recommendation")
        )
        if not is_new_rec:
            continue
        for kw in node.keywords:
            if kw.arg != "priority":
                continue
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                if kw.value.value not in VALID_PRIORITIES:
                    hits.append((kw.value.lineno, kw.value.value))
    return hits


def test_no_invalid_priority_in_purview_recommendations():
    py_files = list(PURVIEW_DIR.rglob("*.py"))
    assert py_files, f"No .py files found under {PURVIEW_DIR}"

    failures = []
    for filepath in sorted(py_files):
        for lineno, value in _invalid_priority_literals(filepath):
            rel = filepath.relative_to(PURVIEW_DIR.parent.parent)
            failures.append(
                f"  {rel}:{lineno}: priority={value!r} (must be 'High', 'Medium', 'Low', or '')"
            )

    assert not failures, (
        "Invalid priority= values in Recommendations/purview/ would raise ValueError "
        "in new_recommendation() and silently wipe all Purview recommendations (LEM-611):\n"
        + "\n".join(failures)
    )
