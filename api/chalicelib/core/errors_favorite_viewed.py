from chalicelib.utils import pg_client


def add_favorite_error(project_id, user_id, error_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                '\\\x1f                INSERT INTO public.user_favorite_errors \x1f                    (user_id, error_id) \x1f                VALUES \x1f                    (%(userId)s,%(error_id)s);',
                {"userId": user_id, "error_id": error_id},
            )
        )

    return {"errorId": error_id, "favorite": True}


def remove_favorite_error(project_id, user_id, error_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                '\\\x1f                        DELETE FROM public.user_favorite_errors                          \x1f                        WHERE \x1f                            user_id = %(userId)s\x1f                            AND error_id = %(error_id)s;',
                {"userId": user_id, "error_id": error_id},
            )
        )

    return {"errorId": error_id, "favorite": False}


def favorite_error(project_id, user_id, error_id):
    exists, favorite = error_exists_and_favorite(user_id=user_id, error_id=error_id)
    if not exists:
        return {"errors": ["cannot bookmark non-rehydrated errors"]}
    if favorite:
        return remove_favorite_error(project_id=project_id, user_id=user_id, error_id=error_id)
    return add_favorite_error(project_id=project_id, user_id=user_id, error_id=error_id)


def error_exists_and_favorite(user_id, error_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                """SELECT errors.error_id AS exists, ufe.error_id AS favorite
                    FROM public.errors
                             LEFT JOIN (SELECT error_id FROM public.user_favorite_errors WHERE user_id = %(userId)s) AS ufe USING (error_id)
                    WHERE error_id = %(error_id)s;""",
                {"userId": user_id, "error_id": error_id})
        )
        r = cur.fetchone()
        if r is None:
            return False, False
        return True, r.get("favorite") is not None


def add_viewed_error(project_id, user_id, error_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify("""\
                INSERT INTO public.user_viewed_errors 
                    (user_id, error_id) 
                VALUES 
                    (%(userId)s,%(error_id)s);""",
                        {"userId": user_id, "error_id": error_id})
        )


def viewed_error_exists(user_id, error_id):
    with pg_client.PostgresClient() as cur:
        query = cur.mogrify(
            """SELECT 
                    errors.error_id AS hydrated,
                    COALESCE((SELECT TRUE
                                         FROM public.user_viewed_errors AS ve
                                         WHERE ve.error_id = %(error_id)s
                                           AND ve.user_id = %(userId)s LIMIT 1), FALSE) AS viewed                                                
                FROM public.errors
                WHERE error_id = %(error_id)s""",
            {"userId": user_id, "error_id": error_id})
        cur.execute(
            query=query
        )
        r = cur.fetchone()
        if r:
            return r.get("viewed")
    return True


def viewed_error(project_id, user_id, error_id):
    if viewed_error_exists(user_id=user_id, error_id=error_id):
        return None
    return add_viewed_error(project_id=project_id, user_id=user_id, error_id=error_id)
