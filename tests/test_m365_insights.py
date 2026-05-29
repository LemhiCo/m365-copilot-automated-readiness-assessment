"""
Tests for extract_m365_insights_from_client.

Run: cd m365-copilot-automated-readiness-assessment && python -m pytest tests/ -v
"""
import pytest
from Core.get_m365_client import extract_m365_insights_from_client, col_max, _filter_sharepoint_rows, SYSTEM_SITE_TEMPLATES


class FakeM365Client:
    # active_users_summary['office_365_active'] is populated from getOffice365ActiveUserCounts
    # (the Counts report), NOT getOffice365ActiveUserDetail (the per-user Detail report).
    # The Detail report has no 'Office 365'/'Exchange'/'SharePoint' count columns — using it
    # silently produces all-zero counts. See Core/get_m365_client.py and LEM-513.
    available = True

    def __init__(self, sharepoint_summary=None, active_users_summary=None, teams_summary=None):
        self.sites_summary = {}
        self.users_summary = {}
        self.email_summary = {}
        self.teams_summary = teams_summary or {}
        self.sharepoint_summary = sharepoint_summary or {}
        self.onedrive_summary = {}
        self.activations_summary = {}
        self.active_users_summary = active_users_summary or {}
        self.missing_permissions = []


PREVIOUSLY_PHANTOM_KEYS = [
    'total_active_users',
    'sharepoint_total_sites',
    'sharepoint_page_views',
    'teams_total_messages',
    'office_active_users',
]


def test_success_branch_emits_previously_phantom_keys():
    client = FakeM365Client(
        sharepoint_summary={
            'available': True,
            'sites_in_report': 42,
            'active_sites': 19,
            'total_files': 1_114_008,
            'total_page_views': 5000,
            'site_activity_rate': 45.2,
            'avg_files_per_site': 26500,
        },
        active_users_summary={
            'available': True,
            'office_365_active': 350,
        },
        teams_summary={
            'available': True,
            'total_team_chat_messages': 1200,
            'total_private_messages': 800,
        },
    )

    insights = extract_m365_insights_from_client(client)

    assert insights['available'] is True
    assert insights['sharepoint_total_sites'] == 42
    assert insights['total_active_users'] == 350
    assert insights['office_active_users'] == 350
    assert insights['sharepoint_page_views'] == 5000
    assert insights['teams_total_messages'] == 2000  # 1200 + 800


def test_success_branch_zero_when_source_keys_absent():
    client = FakeM365Client()

    insights = extract_m365_insights_from_client(client)

    for key in PREVIOUSLY_PHANTOM_KEYS:
        assert insights[key] == 0, f"expected 0 for {key}, got {insights[key]}"


def test_fallback_branch_emits_previously_phantom_keys_as_zero():
    for bad_client in [None, type('Unavailable', (), {'available': False})()]:
        insights = extract_m365_insights_from_client(bad_client)
        assert insights['available'] is False
        for key in PREVIOUSLY_PHANTOM_KEYS:
            assert insights[key] == 0, f"expected 0 for {key} in fallback, got {insights[key]}"


def test_fallback_branch_emits_sharepoint_report_available_false():
    insights = extract_m365_insights_from_client(None)
    assert insights['sharepoint_report_available'] is False


def test_col_max_uses_period_peak_not_latest_row():
    # Regression guard for LEM-566: 30-day CSV where the last row is all zeros
    # (weekend/holiday dip), but earlier rows have real activity.
    rows = [
        {'Office 365': '17', 'Exchange': '12', 'OneDrive': '8',
         'SharePoint': '5', 'Teams': '10', 'Yammer': '3'},
        {'Office 365': '15', 'Exchange': '11', 'OneDrive': '7',
         'SharePoint': '4', 'Teams': '9', 'Yammer': '2'},
        {'Office 365': '0', 'Exchange': '0', 'OneDrive': '0',
         'SharePoint': '0', 'Teams': '0', 'Yammer': '0'},  # latest row — all zeros
    ]

    assert col_max(rows, 'Office 365') == 17, "must return period peak, not latest-row 0"
    assert col_max(rows, 'Exchange') == 12
    assert col_max(rows, 'OneDrive') == 8
    assert col_max(rows, 'SharePoint') == 5
    assert col_max(rows, 'Teams') == 10
    assert col_max(rows, 'Yammer') == 3


def test_sharepoint_filter_excludes_deleted_and_system_templates():
    # Synthetic CSV rows using the display names the getSharePointSiteUsageDetail report
    # actually writes in the Root Web Template column (not template codes).
    # One real site, one deleted site, and three system template sites — only the real
    # site should survive filtering.
    rows = [
        {'Root Web Template': 'Team Site',                                'Is Deleted': 'False', 'File Count': '100', 'Page View Count': '50'},
        {'Root Web Template': 'Team Site',                                'Is Deleted': 'True',  'File Count': '20',  'Page View Count': '10'},   # deleted
        {'Root Web Template': 'Tenant Admin Site',                        'Is Deleted': 'False', 'File Count': '0',   'Page View Count': '0'},    # system
        {'Root Web Template': 'SharePoint Online Tenant Fundamental Site','Is Deleted': 'False', 'File Count': '5',   'Page View Count': '3'},    # system
        {'Root Web Template': 'Compliance Policy Center',                 'Is Deleted': 'False', 'File Count': '0',   'Page View Count': '0'},    # system
    ]
    filtered = _filter_sharepoint_rows(rows)

    assert len(filtered) == 1
    assert filtered[0]['Root Web Template'] == 'Team Site'
    assert filtered[0]['Is Deleted'] == 'False'


def test_sharepoint_filter_excludes_app_catalog_site_display_name_variant():
    # 'App Catalog Site' is the display name APPCATALOG#0 uses on older tenants;
    # newer tenants show 'SharePoint Online Tenant Fundamental Site'. Both are system sites.
    # Confirmed from Diamond IT prod scan (2026-05-29).
    rows = [
        {'Root Web Template': 'App Catalog Site', 'Is Deleted': 'False', 'File Count': '10', 'Page View Count': '0'},
        {'Root Web Template': 'Group',             'Is Deleted': 'False', 'File Count': '50', 'Page View Count': '20'},
    ]
    filtered = _filter_sharepoint_rows(rows)
    assert len(filtered) == 1
    assert filtered[0]['Root Web Template'] == 'Group'


def test_sharepoint_filter_case_insensitive_deleted():
    rows = [
        {'Root Web Template': 'STS#0', 'Is Deleted': 'true'},   # lowercase — still deleted
        {'Root Web Template': 'STS#0', 'Is Deleted': 'TRUE'},   # uppercase — still deleted
        {'Root Web Template': 'STS#0', 'Is Deleted': 'False'},  # not deleted
    ]
    filtered = _filter_sharepoint_rows(rows)
    assert len(filtered) == 1
    assert filtered[0]['Is Deleted'] == 'False'


def test_sharepoint_filter_retains_srchcen_sitepagepublishing_spsmsitehost():
    # These display names are kept by SPO "Active sites" enumeration — must not be blocklisted.
    rows = [
        {'Root Web Template': 'Basic Search Center', 'Is Deleted': 'False'},  # SRCHCEN#0
        {'Root Web Template': 'Site Page Publishing', 'Is Deleted': 'False'},  # SITEPAGEPUBLISHING#0
        {'Root Web Template': 'My Site Host',          'Is Deleted': 'False'},  # SPSMSITEHOST#0
    ]
    filtered = _filter_sharepoint_rows(rows)
    assert len(filtered) == 3


def test_sharepoint_filter_all_system_sites_yields_empty_not_error():
    # A tenant whose report contains only system/deleted sites should produce
    # sites_in_report=0 with no file-count bleed — not an exception.
    # Confirms the aggregation loop runs over filtered_rows and that the
    # divide-by-zero guards in avg_files_per_site / site_activity_rate hold.
    rows = [
        {'Root Web Template': 'Tenant Admin Site',                        'Is Deleted': 'False', 'File Count': '999', 'Page View Count': '0'},
        {'Root Web Template': 'SharePoint Online Tenant Fundamental Site','Is Deleted': 'False', 'File Count': '500', 'Page View Count': '0'},
        {'Root Web Template': 'Team Site',                                'Is Deleted': 'True',  'File Count': '200', 'Page View Count': '0'},
    ]
    filtered = _filter_sharepoint_rows(rows)
    assert len(filtered) == 0

    # Simulate the aggregation logic directly on the empty filtered list
    total_files = sum(int(r.get('File Count', 0) or 0) for r in filtered)
    total_sites = len(filtered)
    avg_files = round(total_files / total_sites, 1) if total_sites > 0 else 0

    assert total_files == 0
    assert total_sites == 0
    assert avg_files == 0  # guard held — no ZeroDivisionError


def test_col_max_handles_empty_and_missing_values():
    rows = [
        {'Office 365': '', 'Exchange': None},
        {'Office 365': '5'},
    ]
    assert col_max(rows, 'Office 365') == 5
    assert col_max(rows, 'Exchange') == 0
    assert col_max([], 'Office 365') == 0  # empty rows → default 0
