from chalicelib.core import integration_github, integration_jira_cloud
from chalicelib.utils import pg_client

SUPPORTED_TOOLS = [integration_github.PROVIDER, integration_jira_cloud.PROVIDER]


def get_available_integrations(user_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                "\\\x1f                    SELECT EXISTS((SELECT 1\x1f                               FROM public.oauth_authentication\x1f                               WHERE user_id = %(user_id)s\x1f                                 AND provider = 'github')) AS github,\x1f                           EXISTS((SELECT 1\x1f                                   FROM public.jira_cloud\x1f                                   WHERE user_id = %(user_id)s))       AS jira;",
                {"user_id": user_id},
            )
        )

        current_integrations = cur.fetchone()
    return dict(current_integrations)


def __get_default_integration(user_id):
    current_integrations = get_available_integrations(user_id)
    return integration_github.PROVIDER if current_integrations["github"] else integration_jira_cloud.PROVIDER if \
        current_integrations["jira"] else None


def get_integration(tenant_id, user_id, tool=None):
    if tool is None:
        tool = __get_default_integration(user_id=user_id)
    if tool is None:
        return {"errors": ['no issue tracking tool found']}, None
    tool = tool.upper()
    if tool not in SUPPORTED_TOOLS:
        return {"errors": [f"issue tracking tool not supported yet, available: {SUPPORTED_TOOLS}"]}, None
    if tool == integration_jira_cloud.PROVIDER:
        return None, integration_jira_cloud.JIRAIntegration(tenant_id=tenant_id, user_id=user_id)
    elif tool == integration_github.PROVIDER:
        return None, integration_github.GitHubIntegration(tenant_id=tenant_id, user_id=user_id)
    return {"errors": ["lost integration"]}, None
