"""
Regression guard for LEM-567: recommendation text that references org size must
use total_users (directory count) not total_active_users (peak-period active).

The bug: multiple Recommendations/m365/*.py files used {total_active_users:,} in
observation/recommendation text where the author meant "size of org", producing
absurd output like "17 active users out of 1 total users" on tenants where most
users are inactive in a given period.
"""
import importlib.util
from pathlib import Path

# Import directly by file path to avoid Recommendations/m365/__init__.py,
# which triggers a progress tracker that requires prior setup.
_rec_dir = Path(__file__).parent.parent / "Recommendations" / "m365"

def _load(name):
    spec = importlib.util.spec_from_file_location(name, _rec_dir / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.get_recommendation

exchange_analytics_rec = _load("EXCHANGE_ANALYTICS")


INSIGHTS_SMALL_TENANT = {
    'available': True,
    'total_users': 17,        # directory size — 17 accounts in Entra
    'total_active_users': 1,  # peak-period active — only 1 user active on busiest day
    'email_active_users': 1,
    'teams_active_users': 0,
    'teams_total_meetings': 0,
}


def test_exchange_analytics_org_size_uses_total_users():
    recs = exchange_analytics_rec("EXCHANGE_S1", status="Success", m365_insights=INSIGHTS_SMALL_TENANT)
    observations = " ".join(r["Observation"] for r in recs)
    assert "out of 17 total users" in observations, (
        f"Expected directory size (total_users=17) in observation text, "
        f"not peak-active (total_active_users=1). Got: {observations!r}"
    )
    assert "out of 1 total users" not in observations, (
        "Observation text incorrectly used total_active_users as org size."
    )
