from chalicelib.utils import pg_client
import requests


def process_data(data, edition='fos'):
    return {
        'edition': edition,
        'tracking': data["opt_out"],
        'version': data["version_number"],
        'user_id': data["user_id"],
        'owner_email': None if data["opt_out"] else data["email"],
        'organization_name': None if data["opt_out"] else data["name"],
        'users_count': data["t_users"],
        'projects_count': data["t_projects"],
        'sessions_count': data["t_sessions"],
        'integrations_count': data["t_integrations"]
    }


def compute():
    with pg_client.PostgresClient() as cur:
        cur.execute(
            "UPDATE public.tenants\x1f                SET t_integrations = COALESCE((SELECT COUNT(DISTINCT provider) FROM public.integrations) +\x1f                                              (SELECT COUNT(*) FROM public.webhooks WHERE type = 'slack') +\x1f                                              (SELECT COUNT(*) FROM public.jira_cloud), 0),\x1f                    t_projects=COALESCE((SELECT COUNT(*) FROM public.projects WHERE deleted_at ISNULL), 0),\x1f                    t_sessions=COALESCE((SELECT COUNT(*) FROM public.sessions), 0),\x1f                    t_users=COALESCE((SELECT COUNT(*) FROM public.users WHERE deleted_at ISNULL), 0)\x1f                RETURNING *,(SELECT email FROM public.users WHERE role='owner' LIMIT 1);"
        )

        data = cur.fetchone()
        requests.post('https://parrot.asayer.io/os/telemetry', json={"stats": [process_data(data)]})


def new_client():
    with pg_client.PostgresClient() as cur:
        cur.execute(
            "SELECT *, \x1f                (SELECT email FROM public.users WHERE role='owner' LIMIT 1) AS email \x1f                FROM public.tenants;"
        )

        data = cur.fetchone()
        requests.post('https://parrot.asayer.io/os/signup', json=process_data(data))
