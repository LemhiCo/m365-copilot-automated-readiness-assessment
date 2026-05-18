"""
SharePoint (Plan 2) - M365 Copilot & Agent Adoption Recommendation
"""
from Core.new_recommendation import new_recommendation
from Core.friendly_names import get_friendly_sku_name

async def get_recommendation(sku_name, status="Success", client=None, m365_insights=None):
    """
    SharePoint Plan 2 provides the collaborative content platform that Copilot
    uses to find, summarize, and generate insights from organizational knowledge.

    Returns 2-3 recommendations:
    1. License status (active/inactive)
    2. Deployment status (sites deployed, content volume assessment)
    3. Activity insights (if m365_insights available)

    Args:
        sku_name: SKU name where feature is found
        status: Provisioning status
        client: Optional Graph client (unused — kept for signature compatibility)
        m365_insights: Optional pre-computed M365 usage metrics
    """
    feature_name = "SharePoint (Plan 2)"
    friendly_sku = get_friendly_sku_name(sku_name)
    recommendations = []

    # RECOMMENDATION 1: License Status
    if status == "Success":
        recommendations.append(new_recommendation(
            service="M365",
            feature=feature_name,
            observation=f"{feature_name} is active in {friendly_sku}, providing enterprise content management for Copilot",
            recommendation="",
            link_text="SharePoint Documentation",
            link_url="https://learn.microsoft.com/sharepoint/",
            status=status
        ))
    else:
        recommendations.append(new_recommendation(
            service="M365",
            feature=feature_name,
            observation=f"{feature_name} is {status} in {friendly_sku}, limiting Copilot's access to organizational content",
            recommendation=f"Enable {feature_name} to provide the content foundation for M365 Copilot. SharePoint stores the organizational knowledge that Copilot retrieves and reasons over - policies, procedures, project documentation, and institutional knowledge. Copilot uses SharePoint's semantic indexing to understand content relationships and permissions, ensuring AI responses respect your security model. Without SharePoint, Copilot cannot access team sites, document libraries, and collaborative workspaces.",
            link_text="SharePoint as Copilot's Knowledge Base",
            link_url="https://learn.microsoft.com/sharepoint/",
            priority="High",
            status=status
        ))

    # RECOMMENDATION 2: Deployment Check (only if license is active)
    if status == "Success":
        report_available = m365_insights and m365_insights.get('sharepoint_report_available')

        if report_available:
            site_count = m365_insights.get('sharepoint_total_sites', 0)

            if site_count > 10:
                recommendations.append(new_recommendation(
                    service="M365",
                    feature="SharePoint Content Deployment",
                    observation=f"{site_count} SharePoint site(s) deployed with content available for Copilot",
                    recommendation="",
                    link_text="SharePoint Admin Center",
                    link_url="https://admin.microsoft.com/sharepoint",
                    status="Success"
                ))
            elif site_count > 0:
                recommendations.append(new_recommendation(
                    service="M365",
                    feature="SharePoint Content Deployment",
                    observation=f"Only {site_count} SharePoint site(s) deployed - limited content for Copilot to access",
                    recommendation=f"Expand SharePoint deployment to maximize Copilot's effectiveness. Copilot's value grows with content volume - more sites with documents, lists, and knowledge bases mean better AI responses. Create dedicated sites for departments, projects, and knowledge areas. Migrate file shares and local drives to SharePoint to make content searchable by Copilot. Encourage teams to centralize documentation, policies, and procedures in SharePoint for comprehensive AI-powered knowledge retrieval.",
                    link_text="Plan SharePoint Sites",
                    link_url="https://learn.microsoft.com/sharepoint/plan-sites-for-copilot",
                    priority="Medium",
                    status="Warning"
                ))
            else:
                recommendations.append(new_recommendation(
                    service="M365",
                    feature="SharePoint Content Deployment",
                    observation=f"ZERO SharePoint sites deployed - Copilot has no organizational content to access",
                    recommendation=f"URGENT: Deploy SharePoint sites and migrate content immediately. Without SharePoint content, Copilot cannot provide value based on organizational knowledge. Start by creating sites for key departments, projects, and knowledge areas. Migrate critical documents from file shares, network drives, and email attachments to SharePoint. Upload policies, procedures, templates, and institutional knowledge. Copilot's effectiveness depends entirely on accessible content - zero sites means zero organizational intelligence.",
                    link_text="Get Started with SharePoint",
                    link_url="https://learn.microsoft.com/sharepoint/get-started",
                    priority="High",
                    status="Warning"
                ))
        else:
            recommendations.append(new_recommendation(
                service="M365",
                feature="SharePoint Content Deployment",
                observation=f"SharePoint license is active in {friendly_sku}. Content assessment requires manual review.",
                recommendation=f"Assess SharePoint content deployment for Copilot readiness. Copilot's value scales with content volume and quality. Review number of sites, document libraries, and knowledge bases. Ensure teams are using SharePoint rather than file shares or local storage. Migrate legacy content to make it accessible to Copilot. Create sites for departments, projects, and knowledge areas to centralize organizational intelligence.",
                link_text="SharePoint Admin Center",
                link_url="https://admin.microsoft.com/sharepoint",
                priority="Medium",
                status="PendingInput"
            ))

    # RECOMMENDATION 3: Activity Insights (if m365_insights available)
    if status == "Success" and m365_insights and m365_insights.get('sharepoint_report_available'):
        active_sites = m365_insights.get('sharepoint_active_sites', 0)
        total_files = m365_insights.get('sharepoint_total_files', 0)
        total_page_views = m365_insights.get('sharepoint_total_page_views', 0)
        activity_rate = m365_insights.get('sharepoint_activity_rate', 0)

        if activity_rate >= 50 and total_files > 1000:
            recommendations.append(new_recommendation(
                service="M365",
                feature=f"{feature_name} - Usage Activity",
                observation=f"Strong SharePoint engagement: {active_sites} active sites with {total_files:,} files and {activity_rate}% activity rate. Rich content foundation ready for Copilot",
                recommendation="",
                link_text="SharePoint Activity Reports",
                link_url="https://learn.microsoft.com/microsoft-365/admin/activity-reports/sharepoint-site-usage",
                status="Success"
            ))
        elif activity_rate >= 25:
            recommendations.append(new_recommendation(
                service="M365",
                feature=f"{feature_name} - Usage Activity",
                observation=f"Moderate SharePoint activity: {active_sites} active sites with {total_files:,} files ({activity_rate}% activity rate). Content available but engagement could be higher",
                recommendation="Increase SharePoint adoption to maximize Copilot effectiveness. Encourage teams to actively use SharePoint for document collaboration, reduce email attachments in favor of SharePoint links, and ensure content is regularly updated. Higher activity means fresher content for Copilot to surface.",
                link_text="Drive SharePoint Adoption",
                link_url="https://adoption.microsoft.com/sharepoint/",
                priority="Low",
                status="Success"
            ))
        else:
            recommendations.append(new_recommendation(
                service="M365",
                feature=f"{feature_name} - Usage Activity",
                observation=f"Low SharePoint activity detected: Only {activity_rate}% activity rate across {active_sites} sites with {total_files:,} files. Limited engagement reduces Copilot value",
                recommendation="Address low SharePoint adoption to unlock Copilot potential. Low activity suggests content is stale or teams aren't using SharePoint. Audit content freshness, run adoption campaigns, provide training on SharePoint features, and migrate active file shares to SharePoint. Copilot requires current, actively-used content to provide relevant insights.",
                link_text="SharePoint Adoption Resources",
                link_url="https://adoption.microsoft.com/sharepoint/",
                priority="Medium",
                status="Warning"
            ))

    return recommendations
