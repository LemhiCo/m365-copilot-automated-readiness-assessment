"""
Regression guard for LEM-552: recommendation= assignments must not contain
f-string-style placeholders in plain (non-f) string literals.

The bug: nineteen recommendation= lines in Recommendations/m365/*.py were
plain strings like recommendation="... {total_active_users:,} ..." — the
placeholders shipped to customers as literal text instead of formatted numbers.
"""
import ast
import re
from pathlib import Path

RECOMMENDATIONS_ROOT = Path(__file__).parent.parent / "Recommendations"
PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*(?::[^}]*)?\}")


def _plain_recommendation_strings(filepath: Path) -> list[tuple[int, str]]:
    """Return (lineno, value) for plain string recommendation= assignments that contain placeholders."""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.keyword):
            continue
        if node.arg != "recommendation":
            continue
        # Only flag plain strings (Constant), not f-strings (JoinedStr)
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            if PLACEHOLDER_RE.search(node.value.value):
                hits.append((node.value.lineno, node.value.value[:80]))
    return hits


def test_no_plain_format_strings_in_recommendations():
    py_files = list(RECOMMENDATIONS_ROOT.rglob("*.py"))
    assert py_files, f"No .py files found under {RECOMMENDATIONS_ROOT}"

    failures = []
    for filepath in sorted(py_files):
        for lineno, snippet in _plain_recommendation_strings(filepath):
            rel = filepath.relative_to(RECOMMENDATIONS_ROOT.parent)
            failures.append(f"  {rel}:{lineno}: {snippet!r}...")

    assert not failures, (
        "Plain string recommendation= assignments contain f-string-style placeholders.\n"
        "Add the `f` prefix to each:\n" + "\n".join(failures)
    )
