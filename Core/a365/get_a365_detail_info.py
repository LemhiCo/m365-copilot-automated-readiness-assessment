"""A365 package detail data processing helpers.

Receives the list of filtered detail dicts from get_a365_detail_client and
produces one AI executive summary row plus per-category stat observation rows.
"""

import asyncio
import importlib

from Core.new_recommendation import new_recommendation
from Core.spinner import _stdout_lock, get_timestamp

_DETAIL_URL = "https://graph.microsoft.com/beta/copilot/admin/catalog/packages/{id}"


def _fmt(counter_dict, top=None):
    """Turn {label: count} into a readable 'N label, N label' string."""
    items = list(counter_dict.items())
    if top:
        items = items[:top]
    return ", ".join(f"{v} {k}" for k, v in items) if items else "None"


def _stat_detail_recommendations(agg):
    """Build per-category stat recommendation rows from aggregated detail data with Agent 365 guidance."""
    total = agg["sampledCount"]
    recs = []

    def _rec(feature, observation, recommendation, priority):
        recs.append(new_recommendation(
            service="A365",
            feature=feature,
            observation=observation,
            recommendation=recommendation,
            link_text="Agent 365 Documentation",
            link_url="https://learn.microsoft.com/en-us/microsoft-agent-365/",
            priority=priority,
            status="Success",
        ))

    categories = _fmt(agg['byCategory'])
    _rec(
        "Package Detail: Category Distribution",
        f"Category distribution across {total} sampled packages: {categories}.",
        f"Review the category breakdown with your Agent 365 adoption team. Prioritize packages in categories aligned with your automation roadmap (e.g., Collaboration, Productivity). See Agent 365 documentation for guidance on mapping package categories to agent capabilities.",
        "Medium",
    )

    hosts = _fmt(agg['bySupportedHost'])
    _rec(
        "Package Detail: Supported Hosts",
        f"Supported host breakdown ({total} packages): {hosts}.",
        f"Ensure your Agent 365 deployment targets support these hosts. Teams-first packages are ideal for agent distribution; desktop apps may require additional client configuration. Validate host requirements in your deployment plan.",
        "Medium",
    )

    elements = _fmt(agg['byElementType'])
    _rec(
        "Package Detail: Element Types",
        f"Element types observed across {total} packages: {elements}.",
        f"StaticTabs and Bots are common element types in Agent 365 workflows. Plan to extend these packages with agent capabilities via APIs and webhooks. Refer to Agent 365 extensibility documentation for integration patterns.",
        "Medium",
    )

    versions = _fmt(agg['byVersion'], top=10)
    _rec(
        "Package Detail: Version Distribution",
        f"Top manifest versions across {total} packages: {versions}.",
        f"Verify that your Agent 365 agents are compatible with the prevalent manifest versions in your tenant. Outdated versions may limit interoperability. Establish a version management policy aligned with Agent 365 updates.",
        "Low",
    )

    restricted = agg["packagesWithRestrictedAccess"]
    _rec(
        "Package Detail: Restricted Access",
        f"{restricted} of {total} sampled packages have explicit allowedUsersAndGroups restrictions configured."
        if restricted
        else f"None of the {total} sampled packages carry explicit allowedUsersAndGroups restrictions.",
        f"For agents to execute effectively, ensure they have sufficient scope to access required packages. Test Agent 365 user assignments against your package restrictions to prevent access failures. Document scope requirements in your deployment runbook."
        if restricted
        else f"No restrictions detected on sampled packages, which simplifies Agent 365 scope planning. Verify this applies to your full catalog and adjust package-level permissions as needed.",
        "High" if restricted else "Low",
    )

    acquired = agg["packagesWithAcquiredUsers"]
    _rec(
        "Package Detail: User Acquisition",
        f"{acquired} of {total} sampled packages show active user acquisition (non-empty acquireUsersAndGroups)."
        if acquired
        else f"No active user acquisition entries found across the {total} sampled packages.",
        f"These {acquired} package(s) with active acquired users indicate deployment in progress. Ensure Agent 365 agents gain appropriate permissions for these deployed packages. Coordinate agent capability assignment with ongoing package rollouts."
        if acquired
        else f"No user acquisition activity detected. Consider leveraging Agent 365 to drive adoption of available packages in your tenant by extending them with agent-driven workflows.",
        "Medium" if acquired else "Low",
    )

    return recs


async def get_a365_detail_info(details, progress_callback=None):
    """Process A365 package detail list into orchestrator recommendation rows.

    Args:
        details: List of filtered detail dicts from get_a365_detail_client.
        progress_callback: Optional callable(done, total).

    Returns:
        dict with 'available', 'total_details', and 'recommendations'.
    """
    if not details:
        return {"available": False, "recommendations": []}

    valid_details = [d for d in details if isinstance(d, dict)]
    total = len(valid_details)

    if progress_callback:
        progress_callback(0, total)

    try:
        summarize_module = importlib.import_module("Core.a365.copilot_summarizer")
        mode = getattr(summarize_module, "get_runtime_mode")()
    except Exception:
        mode = {"enabled": False}

    executive_summary = None
    agg = None

    if mode.get("enabled") and total > 0:
        try:
            from Core.a365.copilot_summarizer import (
                _aggregate_details,
                _build_detail_statistical_fallback,
                summarize_details_executive,
            )
            agg = _aggregate_details(valid_details)
            ai_text, fallback_text = await asyncio.to_thread(
                summarize_details_executive, valid_details
            )
            executive_summary = ai_text if ai_text else fallback_text
        except Exception as ex:
            with _stdout_lock:
                print(
                    f"[{get_timestamp()}] [WARN] A365 detail summary failed ({type(ex).__name__}); "
                    "using statistical fallback."
                )
            try:
                from Core.a365.copilot_summarizer import (
                    _aggregate_details,
                    _build_detail_statistical_fallback,
                )
                agg = agg or _aggregate_details(valid_details)
                executive_summary = _build_detail_statistical_fallback(agg)
            except Exception:
                executive_summary = f"Package detail metadata retrieved for {total} packages."
    else:
        try:
            from Core.a365.copilot_summarizer import (
                _aggregate_details,
                _build_detail_statistical_fallback,
            )
            agg = _aggregate_details(valid_details)
            executive_summary = _build_detail_statistical_fallback(agg)
        except Exception:
            executive_summary = f"Package detail metadata retrieved for {total} packages."

    recommendations = [
        new_recommendation(
            service="A365",
            feature="Package Detail Overview",
            observation=executive_summary,
            recommendation="Review the detailed breakdown of supported hosts, element types, access restrictions, and user acquisition patterns to align package deployments with Agent 365 integration requirements. Prioritize packages suitable for automation based on supported hosts matching your agent target platforms and element type coverage. Use this analysis to create an Agent 365 rollout strategy that maximizes agent capabilities while respecting access and deployment constraints.",
            priority="High",
            link_text="Agent 365 Documentation",
            link_url="https://learn.microsoft.com/en-us/microsoft-agent-365/",
            status="Success",
        )
    ]

    if agg:
        recommendations.extend(_stat_detail_recommendations(agg))

    if progress_callback:
        progress_callback(total, total)

    return {
        "available": True,
        "total_details": total,
        "recommendations": recommendations,
    }
