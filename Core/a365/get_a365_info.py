"""A365 data processing helpers."""

from Core.get_recommendation import get_recommendation


async def get_a365_info(a365_client):
    """Process A365 package catalog payload into orchestrator output format."""
    if not isinstance(a365_client, dict):
        return {
            'available': False,
            'reason': 'A365 catalog payload is unavailable',
            'recommendations': []
        }

    packages = a365_client.get('value', [])
    if not isinstance(packages, list):
        packages = []

    recommendations = []
    for package in packages:
        if not isinstance(package, dict):
            continue

        feature_name = "CATALOG_PACKAGE"
        sku_name = package.get('displayName') or package.get('name') or package.get('id') or 'A365 Package'
        status = package.get('status') or 'Success'

        rec = get_recommendation('a365', feature_name, sku_name, status, client=package)
        if isinstance(rec, list):
            recommendations.extend(rec)
        else:
            recommendations.append(rec)

    return {
        'available': True,
        'has_a365': True,
        'total_packages': len(packages),
        'packages': packages,
        'recommendations': recommendations
    }
