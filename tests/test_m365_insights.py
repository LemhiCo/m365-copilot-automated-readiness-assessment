"""
Tests for extract_m365_insights_from_client.

Run: cd m365-copilot-automated-readiness-assessment && python -m pytest tests/ -v
"""
import pytest
from Core.get_m365_client import extract_m365_insights_from_client


class FakeM365Client:
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
