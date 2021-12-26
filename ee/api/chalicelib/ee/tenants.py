from chalicelib.utils import pg_client
from chalicelib.utils import helper
from chalicelib.ee import users


def get_by_tenant_id(tenant_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                'SELECT \x1f                       t.tenant_id,\x1f                       t.name,\x1f                       t.api_key,\x1f                       t.created_at,\x1f                        t.edition,\x1f                        t.version_number,\x1f                        t.opt_out\x1f                    FROM public.tenants AS t\x1f                    WHERE t.tenant_id = %(tenantId)s AND t.deleted_at ISNULL\x1f                    LIMIT 1;',
                {"tenantId": tenant_id},
            )
        )

        return helper.dict_to_camel_case(cur.fetchone())


def get_by_api_key(api_key):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                'SELECT \x1f                       t.tenant_id,\x1f                       t.name,\x1f                       t.created_at                        \x1f                    FROM public.tenants AS t\x1f                    WHERE t.api_key = %(api_key)s AND t.deleted_at ISNULL\x1f                    LIMIT 1;',
                {"api_key": api_key},
            )
        )

        return helper.dict_to_camel_case(cur.fetchone())


def generate_new_api_key(tenant_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                'UPDATE public.tenants\x1f                   SET api_key=generate_api_key(20)\x1f                   WHERE tenant_id= %(tenant_id)s AND deleted_at ISNULL\x1f                   RETURNING api_key;',
                {"tenant_id": tenant_id},
            )
        )

        return helper.dict_to_camel_case(cur.fetchone())


def edit_client(tenant_id, changes):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(f"""\
                            UPDATE public.tenants 
                            SET {", ".join([f"{helper.key_to_snake_case(k)} = %({k})s" for k in changes.keys()])}
                            WHERE tenant_id= %(tenant_id)s AND deleted_at ISNULL
                            RETURNING name, opt_out;""",
                        {"tenantId": tenant_id, **changes})
        )
        return helper.dict_to_camel_case(cur.fetchone())


def update(tenant_id, user_id, data):
    admin = users.get(user_id=user_id, tenant_id=tenant_id)

    if not admin["admin"] and not admin["superAdmin"]:
        return {"error": "unauthorized"}
    if "name" not in data and "optOut" not in data:
        return {"errors": ["please provide 'name' of 'optOut' attribute for update"]}
    changes = {}
    if "name" in data:
        changes["name"] = data["name"]
    if "optOut" in data:
        changes["optOut"] = data["optOut"]
    return edit_client(tenant_id=tenant_id, changes=changes)


def get_tenants():
    with pg_client.PostgresClient() as cur:
        cur.execute('SELECT name FROM public.tenants')
        return helper.list_to_camel_case(cur.fetchall())
