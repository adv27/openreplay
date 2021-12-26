import json

from chalicelib.core import authorizers

from chalicelib.utils import helper
from chalicelib.utils import pg_client
from chalicelib.utils import dev
from chalicelib.utils.TimeUTC import TimeUTC
from chalicelib.utils.helper import environ

from chalicelib.core import tenants


def create_new_member(email, password, admin, name, owner=False):
    with pg_client.PostgresClient() as cur:
        query = cur.mogrify(
            "\\\x1f                    WITH u AS (\x1f                        INSERT INTO public.users (email, role, name, data)\x1f                            VALUES (%(email)s, %(role)s, %(name)s, %(data)s)\x1f                            RETURNING user_id,email,role,name,appearance\x1f                    ),\x1f                         au AS (INSERT\x1f                             INTO public.basic_authentication (user_id, password, generated_password)\x1f                                 VALUES ((SELECT user_id FROM u), crypt(%(password)s, gen_salt('bf', 12)), TRUE))\x1f                    SELECT u.user_id                                              AS id,\x1f                           u.email,\x1f                           u.role,\x1f                           u.name,\x1f                           TRUE                                                   AS change_password,\x1f                           (CASE WHEN u.role = 'owner' THEN TRUE ELSE FALSE END)  AS super_admin,\x1f                           (CASE WHEN u.role = 'admin' THEN TRUE ELSE FALSE END)  AS admin,\x1f                           (CASE WHEN u.role = 'member' THEN TRUE ELSE FALSE END) AS member,\x1f                           u.appearance\x1f                    FROM u;",
            {
                "email": email,
                "password": password,
                "role": "owner" if owner else "admin" if admin else "member",
                "name": name,
                "data": json.dumps({"lastAnnouncementView": TimeUTC.now()}),
            },
        )

        cur.execute(
            query
        )
        return helper.dict_to_camel_case(cur.fetchone())


def restore_member(user_id, email, password, admin, name, owner=False):
    with pg_client.PostgresClient() as cur:
        query = cur.mogrify(
            "\\\x1f                    UPDATE public.users\x1f                    SET name= %(name)s,\x1f                        role = %(role)s,\x1f                        deleted_at= NULL,\x1f                        created_at = timezone('utc'::text, now()),\x1f                        api_key= generate_api_key(20)\x1f                    WHERE user_id=%(user_id)s\x1f                    RETURNING user_id                                           AS id,\x1f                           email,\x1f                           role,\x1f                           name,\x1f                           TRUE                                                 AS change_password,\x1f                           (CASE WHEN role = 'owner' THEN TRUE ELSE FALSE END)  AS super_admin,\x1f                           (CASE WHEN role = 'admin' THEN TRUE ELSE FALSE END)  AS admin,\x1f                           (CASE WHEN role = 'member' THEN TRUE ELSE FALSE END) AS member,\x1f                           appearance;",
            {
                "user_id": user_id,
                "email": email,
                "role": "owner" if owner else "admin" if admin else "member",
                "name": name,
            },
        )

        cur.execute(
            query
        )
        result = helper.dict_to_camel_case(cur.fetchone())
        query = cur.mogrify("""\
                    UPDATE public.basic_authentication
                    SET password= crypt(%(password)s, gen_salt('bf', 12)), 
                        generated_password= TRUE,
                        token=NULL,
                        token_requested_at=NULL
                    WHERE user_id=%(user_id)s;""",
                            {"user_id": user_id, "password": password})
        cur.execute(
            query
        )

        return result


def update(tenant_id, user_id, changes):
    AUTH_KEYS = ["password", "generatedPassword", "token"]
    if len(changes.keys()) == 0:
        return None

    sub_query_users = []
    sub_query_bauth = []
    for key in changes.keys():
        if key in AUTH_KEYS:
            if key == "password":
                sub_query_bauth.append("password = crypt(%(password)s, gen_salt('bf', 12))")
                sub_query_bauth.append("changed_at = timezone('utc'::text, now())")
            elif key == "token":
                if changes[key] is not None:
                    sub_query_bauth.append("token = %(token)s")
                    sub_query_bauth.append("token_requested_at = timezone('utc'::text, now())")
                else:
                    sub_query_bauth.append("token = NULL")
                    sub_query_bauth.append("token_requested_at = NULL")
            else:
                sub_query_bauth.append(f"{helper.key_to_snake_case(key)} = %({key})s")
        elif key == "appearance":
            sub_query_users.append('appearance = %(appearance)s::jsonb')
            changes["appearance"] = json.dumps(changes[key])
        else:
            sub_query_users.append(f"{helper.key_to_snake_case(key)} = %({key})s")

    with pg_client.PostgresClient() as cur:
        if sub_query_users:
            cur.execute(
                cur.mogrify(f"""\
                            UPDATE public.users
                            SET {" ,".join(sub_query_users)}
                            FROM public.basic_authentication
                            WHERE users.user_id = %(user_id)s
                              AND users.user_id = basic_authentication.user_id
                            RETURNING users.user_id AS id,
                                users.email,
                                users.role,
                                users.name,
                                basic_authentication.generated_password  AS change_password,
                                (CASE WHEN users.role = 'owner' THEN TRUE ELSE FALSE END) AS super_admin,
                                (CASE WHEN users.role = 'admin' THEN TRUE ELSE FALSE END) AS admin,
                                (CASE WHEN users.role = 'member' THEN TRUE ELSE FALSE END) AS member,
                                users.appearance;""",
                            {"user_id": user_id, **changes})
            )
        if sub_query_bauth:
            cur.execute(
                cur.mogrify(f"""\
                            UPDATE public.basic_authentication
                            SET {" ,".join(sub_query_bauth)}
                            FROM public.users AS users
                            WHERE basic_authentication.user_id = %(user_id)s
                              AND users.user_id = basic_authentication.user_id
                            RETURNING users.user_id AS id,
                                users.email,
                                users.role,
                                users.name,
                                basic_authentication.generated_password  AS change_password,
                                (CASE WHEN users.role = 'owner' THEN TRUE ELSE FALSE END) AS super_admin,
                                (CASE WHEN users.role = 'admin' THEN TRUE ELSE FALSE END) AS admin,
                                (CASE WHEN users.role = 'member' THEN TRUE ELSE FALSE END) AS member,
                                users.appearance;""",
                            {"user_id": user_id, **changes})
            )

        return helper.dict_to_camel_case(cur.fetchone())


def create_member(tenant_id, user_id, data):
    admin = get(tenant_id=tenant_id, user_id=user_id)
    if not admin["admin"] and not admin["superAdmin"]:
        return {"errors": ["unauthorized"]}
    if data.get("userId") is not None:
        return {"errors": ["please use POST/PUT /client/members/{memberId} for update"]}
    user = get_by_email_only(email=data["email"])
    if user:
        return {"errors": ["user already exists"]}
    name = data.get("name", None)
    if name is not None and not helper.is_alphabet_latin_space(name):
        return {"errors": ["invalid user name"]}
    if name is None:
        name = data["email"]
    temp_pass = helper.generate_salt()[:8]
    user = get_deleted_user_by_email(email=data["email"])
    if user is not None:
        new_member = restore_member(email=data["email"], password=temp_pass,
                                    admin=data.get("admin", False), name=name, user_id=user["userId"])
    else:
        new_member = create_new_member(email=data["email"], password=temp_pass,
                                       admin=data.get("admin", False), name=name)

    helper.async_post(environ['email_basic'] % 'member_invitation',
                      {
                          "email": data["email"],
                          "userName": data["email"],
                          "tempPassword": temp_pass,
                          "clientId": tenants.get_by_tenant_id(tenant_id)["name"],
                          "senderName": admin["name"]
                      })
    return {"data": new_member}


def get(user_id, tenant_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                "SELECT \x1f                        users.user_id AS id,\x1f                        email, \x1f                        role, \x1f                        name, \x1f                        basic_authentication.generated_password,\x1f                        (CASE WHEN role = 'owner' THEN TRUE ELSE FALSE END)  AS super_admin,\x1f                        (CASE WHEN role = 'admin' THEN TRUE ELSE FALSE END)  AS admin,\x1f                        (CASE WHEN role = 'member' THEN TRUE ELSE FALSE END) AS member,\x1f                        appearance,\x1f                        api_key\x1f                    FROM public.users LEFT JOIN public.basic_authentication ON users.user_id=basic_authentication.user_id  \x1f                    WHERE\x1f                     users.user_id = %(userId)s\x1f                     AND deleted_at IS NULL\x1f                    LIMIT 1;",
                {"userId": user_id},
            )
        )

        r = cur.fetchone()
        return helper.dict_to_camel_case(r, ignore_keys=["appearance"])


def generate_new_api_key(user_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                'UPDATE public.users\x1f                    SET api_key=generate_api_key(20)\x1f                    WHERE\x1f                     users.user_id = %(userId)s\x1f                     AND deleted_at IS NULL\x1f                    RETURNING api_key;',
                {"userId": user_id},
            )
        )

        r = cur.fetchone()
    return helper.dict_to_camel_case(r)


def edit(user_id_to_update, tenant_id, changes, editor_id):
    ALLOW_EDIT = ["name", "email", "admin", "appearance"]
    user = get(user_id=user_id_to_update, tenant_id=tenant_id)
    if editor_id != user_id_to_update or "admin" in changes and changes["admin"] != user["admin"]:
        admin = get(tenant_id=tenant_id, user_id=editor_id)
        if not admin["superAdmin"] and not admin["admin"]:
            return {"errors": ["unauthorized"]}

    keys = list(changes.keys())
    for k in keys:
        if k not in ALLOW_EDIT:
            changes.pop(k)
    keys = list(changes.keys())

    if keys:
        if "email" in keys and changes["email"] != user["email"]:
            if email_exists(changes["email"]):
                return {"errors": ["email already exists."]}
            if get_deleted_user_by_email(changes["email"]) is not None:
                return {"errors": ["email previously deleted."]}
        if "admin" in keys:
            changes["role"] = "admin" if changes.pop("admin") else "member"
        if len(changes.keys()) > 0:
            updated_user = update(tenant_id=tenant_id, user_id=user_id_to_update, changes=changes)

            return {"data": updated_user}
    return {"data": user}


def get_by_email_only(email):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                "SELECT \x1f                        users.user_id AS id,\x1f                        1 AS tenant_id,\x1f                        users.email, \x1f                        users.role, \x1f                        users.name, \x1f                        basic_authentication.generated_password,\x1f                        (CASE WHEN users.role = 'owner' THEN TRUE ELSE FALSE END)  AS super_admin,\x1f                        (CASE WHEN users.role = 'admin' THEN TRUE ELSE FALSE END)  AS admin,\x1f                        (CASE WHEN users.role = 'member' THEN TRUE ELSE FALSE END) AS member\x1f                    FROM public.users LEFT JOIN public.basic_authentication ON users.user_id=basic_authentication.user_id\x1f                    WHERE\x1f                     users.email = %(email)s                     \x1f                     AND users.deleted_at IS NULL;",
                {"email": email},
            )
        )

        r = cur.fetchall()
    return helper.list_to_camel_case(r)


def get_by_email_reset(email, reset_token):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                "SELECT \x1f                        users.user_id AS id,\x1f                        1 AS tenant_id,\x1f                        users.email, \x1f                        users.role, \x1f                        users.name, \x1f                        basic_authentication.generated_password,\x1f                        (CASE WHEN users.role = 'owner' THEN TRUE ELSE FALSE END)  AS super_admin,\x1f                        (CASE WHEN users.role = 'admin' THEN TRUE ELSE FALSE END)  AS admin,\x1f                        (CASE WHEN users.role = 'member' THEN TRUE ELSE FALSE END) AS member\x1f                    FROM public.users LEFT JOIN public.basic_authentication ON users.user_id=basic_authentication.user_id\x1f                    WHERE\x1f                     users.email = %(email)s\x1f                     AND basic_authentication.token =%(token)s                   \x1f                     AND users.deleted_at IS NULL",
                {"email": email, "token": reset_token},
            )
        )

        r = cur.fetchone()
    return helper.dict_to_camel_case(r)


def get_members(tenant_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            "SELECT \x1f                        users.user_id AS id,\x1f                        users.email, \x1f                        users.role, \x1f                        users.name, \x1f                        basic_authentication.generated_password,\x1f                        (CASE WHEN users.role = 'owner' THEN TRUE ELSE FALSE END)  AS super_admin,\x1f                        (CASE WHEN users.role = 'admin' THEN TRUE ELSE FALSE END)  AS admin,\x1f                        (CASE WHEN users.role = 'member' THEN TRUE ELSE FALSE END) AS member \x1f                    FROM public.users LEFT JOIN public.basic_authentication ON users.user_id=basic_authentication.user_id \x1f                    WHERE users.deleted_at IS NULL\x1f                    ORDER BY name, id"
        )

        r = cur.fetchall()
        if len(r):
            return helper.list_to_camel_case(r)

    return []


def delete_member(user_id, tenant_id, id_to_delete):
    if user_id == id_to_delete:
        return {"errors": ["unauthorized, cannot delete self"]}

    admin = get(user_id=user_id, tenant_id=tenant_id)
    if admin["member"]:
        return {"errors": ["unauthorized"]}

    to_delete = get(user_id=id_to_delete, tenant_id=tenant_id)
    if to_delete is None:
        return {"errors": ["not found"]}

    if to_delete["superAdmin"]:
        return {"errors": ["cannot delete super admin"]}

    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                "UPDATE public.users\x1f                           SET deleted_at = timezone('utc'::text, now()) \x1f                           WHERE user_id=%(user_id)s;",
                {"user_id": id_to_delete},
            )
        )

    return {"data": get_members(tenant_id=tenant_id)}


def change_password(tenant_id, user_id, email, old_password, new_password):
    item = get(tenant_id=tenant_id, user_id=user_id)
    if item is None:
        return {"errors": ["access denied"]}
    if old_password == new_password:
        return {"errors": ["old and new password are the same"]}
    auth = authenticate(email, old_password, for_change_password=True)
    if auth is None:
        return {"errors": ["wrong password"]}
    changes = {"password": new_password, "generatedPassword": False}
    return {"data": update(tenant_id=tenant_id, user_id=user_id, changes=changes),
            "jwt": authenticate(email, new_password)["jwt"]}


def count_members():
    with pg_client.PostgresClient() as cur:
        cur.execute("""SELECT COUNT(user_id) 
                        FROM public.users WHERE deleted_at IS NULL;""")
        r = cur.fetchone()
    return r["count"]


def email_exists(email):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                'SELECT \x1f                        count(user_id)                        \x1f                    FROM public.users\x1f                    WHERE\x1f                     email = %(email)s\x1f                     AND deleted_at IS NULL\x1f                    LIMIT 1;',
                {"email": email},
            )
        )

        r = cur.fetchone()
    return r["count"] > 0


def get_deleted_user_by_email(email):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                'SELECT \x1f                        *                        \x1f                    FROM public.users\x1f                    WHERE\x1f                     email = %(email)s\x1f                     AND deleted_at NOTNULL\x1f                    LIMIT 1;',
                {"email": email},
            )
        )

        r = cur.fetchone()
    return helper.dict_to_camel_case(r)


def auth_exists(user_id, tenant_id, jwt_iat, jwt_aud):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                'SELECT user_id AS id,jwt_iat, changed_at FROM public.users INNER JOIN public.basic_authentication USING(user_id) WHERE user_id = %(userId)s AND deleted_at IS NULL LIMIT 1;',
                {"userId": user_id},
            )
        )

        r = cur.fetchone()
        return r is not None \
               and r.get("jwt_iat") is not None \
               and (abs(jwt_iat - TimeUTC.datetime_to_timestamp(r["jwt_iat"]) // 1000) <= 1 \
                    or (jwt_aud.startswith("plugin") \
                        and (r["changed_at"] is None \
                             or jwt_iat >= (TimeUTC.datetime_to_timestamp(r["changed_at"]) // 1000)))
                    )


@dev.timed
def authenticate(email, password, for_change_password=False, for_plugin=False):
    with pg_client.PostgresClient() as cur:
        query = cur.mogrify(
            "SELECT \x1f                    users.user_id AS id,\x1f                    1 AS tenant_id,\x1f                    users.role,\x1f                    users.name,\x1f                    basic_authentication.generated_password AS change_password,\x1f                    (CASE WHEN users.role = 'owner' THEN TRUE ELSE FALSE END)  AS super_admin,\x1f                    (CASE WHEN users.role = 'admin' THEN TRUE ELSE FALSE END)  AS admin,\x1f                    (CASE WHEN users.role = 'member' THEN TRUE ELSE FALSE END) AS member,\x1f                    users.appearance\x1f                FROM public.users INNER JOIN public.basic_authentication USING(user_id)\x1f                WHERE users.email = %(email)s \x1f                    AND basic_authentication.password = crypt(%(password)s, basic_authentication.password)\x1f                    AND basic_authentication.user_id = (SELECT su.user_id FROM public.users AS su WHERE su.email=%(email)s AND su.deleted_at IS NULL LIMIT 1)\x1f                LIMIT 1;",
            {"email": email, "password": password},
        )


        cur.execute(query)
        r = cur.fetchone()

        if r is not None:
            if for_change_password:
                return True
            r = helper.dict_to_camel_case(r, ignore_keys=["appearance"])
            query = cur.mogrify(
                "UPDATE public.users\x1f                   SET jwt_iat = timezone('utc'::text, now())\x1f                   WHERE user_id = %(user_id)s \x1f                   RETURNING jwt_iat;",
                {"user_id": r["id"]},
            )

            cur.execute(query)
            return {
                "jwt": authorizers.generate_jwt(r['id'], r['tenantId'],
                                                TimeUTC.datetime_to_timestamp(cur.fetchone()["jwt_iat"]),
                                                aud=f"plugin:{helper.get_stage_name()}" if for_plugin else f"front:{helper.get_stage_name()}"),
                "email": email,
                **r
            }
    return None
