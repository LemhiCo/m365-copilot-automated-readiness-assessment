"""Generic A365 catalog package recommendation builder."""

from Core.new_recommendation import new_recommendation


def _trim(value, max_len=180):
    """Return a compact single-line representation for report readability."""
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return f"{text[:max_len - 3]}..."


def _package_name(package_row, fallback):
    for key in ("displayName", "name", "title"):
        val = package_row.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return fallback or "A365 Package"


def get_recommendation(sku_name, status="Success", client=None):
    """Create one observation recommendation from a single A365 package row."""
    package = client if isinstance(client, dict) else {}

    package_name = _package_name(package, sku_name)
    package_id = _trim(package.get("id") or package.get("packageId") or "Unknown")
    package_type = _trim(package.get("type") or package.get("category") or "Unspecified")

    tags = package.get("tags")
    if isinstance(tags, list):
        tags_text = _trim(", ".join(str(t) for t in tags if t is not None), max_len=120)
    else:
        tags_text = _trim(tags, max_len=120) or "None"

    observation = (
        f"Catalog package discovered: {package_name}. "
        f"Id: {package_id}. Type: {package_type}. Tags: {tags_text}."
    )

    return new_recommendation(
        service="A365",
        feature=package_name,
        observation=observation,
        recommendation="",
        link_text="Copilot Package Catalog API",
        link_url="https://graph.microsoft.com/beta/copilot/admin/catalog/packages",
        status=status or "Success"
    )
