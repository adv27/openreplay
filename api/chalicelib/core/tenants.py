from chalicelib.utils import pg_client
from chalicelib.utils import helper
from chalicelib.core import users


def get_by_tenant_id(tenant_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                'SELECT \x1f                       tenant_id,\x1f                       name,\x1f                       api_key,\x1f                       created_at,\x1f                        edition,\x1f                        version_number,\x1f                        opt_out\x1f                    FROM public.tenants\x1f                    LIMIT 1;',
                {"tenantId": tenant_id},
            )
        )

        return helper.dict_to_camel_case(cur.fetchone())


def get_by_api_key(api_key):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                'SELECT \x1f                       1 AS tenant_id,\x1f                       name,\x1f                       created_at                       \x1f                    FROM public.tenants\x1f                    WHERE api_key = %(api_key)s\x1f                    LIMIT 1;',
                {"api_key": api_key},
            )
        )

        return helper.dict_to_camel_case(cur.fetchone())


def generate_new_api_key(tenant_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                'UPDATE public.tenants\x1f                    SET api_key=generate_api_key(20)\x1f                    RETURNING api_key;',
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
