from chalicelib.utils import pg_client
import requests

from chalicelib.core.telemetry import process_data


def compute():
    with pg_client.PostgresClient() as cur:
        cur.execute(
            "UPDATE public.tenants\x1f                SET t_integrations = COALESCE((SELECT COUNT(DISTINCT provider)\x1f                                               FROM public.integrations\x1f                                                        INNER JOIN public.projects USING (project_id)\x1f                                               WHERE projects.tenant_id = all_tenants.tenant_id) +\x1f                                              (SELECT COUNT(*)\x1f                                               FROM public.webhooks\x1f                                               WHERE webhooks.tenant_id = all_tenants.tenant_id\x1f                                                 AND type = 'slack') +\x1f                                              (SELECT COUNT(*)\x1f                                               FROM public.jira_cloud\x1f                                                        INNER JOIN public.users USING (user_id)\x1f                                               WHERE users.tenant_id = all_tenants.tenant_id), 0),\x1f                    t_projects=COALESCE((SELECT COUNT(*)\x1f                                         FROM public.projects\x1f                                         WHERE deleted_at ISNULL\x1f                                           AND projects.tenant_id = all_tenants.tenant_id), 0),\x1f                    t_sessions=COALESCE((SELECT COUNT(*)\x1f                                         FROM public.sessions\x1f                                                  INNER JOIN public.projects USING (project_id)\x1f                                         WHERE projects.tenant_id = all_tenants.tenant_id), 0),\x1f                    t_users=COALESCE((SELECT COUNT(*)\x1f                                      FROM public.users\x1f                                      WHERE deleted_at ISNULL\x1f                                        AND users.tenant_id = all_tenants.tenant_id), 0)\x1f                FROM (\x1f                         SELECT tenant_id\x1f                         FROM public.tenants\x1f                     ) AS all_tenants\x1f                WHERE tenants.tenant_id = all_tenants.tenant_id\x1f                RETURNING *,(SELECT email FROM users_ee WHERE role = 'owner' AND users_ee.tenant_id = tenants.tenant_id LIMIT 1);"
        )

        data = cur.fetchall()
        requests.post('https://parrot.asayer.io/os/telemetry',
                      json={"stats": [process_data(d, edition='ee') for d in data]})


def new_client(tenant_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                'SELECT *,\x1f                            (SELECT email FROM public.users WHERE tenant_id=%(tenant_id)s) AS email\x1f                            FROM public.tenants \x1f                            WHERE tenant_id=%(tenant_id)s;',
                {"tenant_id": tenant_id},
            )
        )

        data = cur.fetchone()
        requests.post('https://parrot.asayer.io/os/signup', json=process_data(data, edition='ee'))
