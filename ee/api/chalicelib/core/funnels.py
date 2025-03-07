import chalicelib.utils.helper
from chalicelib.core import events, significance, sessions
from chalicelib.utils.TimeUTC import TimeUTC

from chalicelib.utils import helper, pg_client
from chalicelib.utils import dev
import json

REMOVE_KEYS = ["key", "_key", "startDate", "endDate"]

ALLOW_UPDATE_FOR = ["name", "filter"]


def filter_stages(stages):
    ALLOW_TYPES = [events.event_type.CLICK.ui_type, events.event_type.INPUT.ui_type,
                   events.event_type.LOCATION.ui_type, events.event_type.CUSTOM.ui_type,
                   events.event_type.CLICK_IOS.ui_type, events.event_type.INPUT_IOS.ui_type,
                   events.event_type.VIEW_IOS.ui_type, events.event_type.CUSTOM_IOS.ui_type, ]
    return [s for s in stages if s["type"] in ALLOW_TYPES and s.get("value") is not None]


def create(project_id, user_id, name, filter, is_public):
    helper.delete_keys_from_dict(filter, REMOVE_KEYS)
    filter["events"] = filter_stages(stages=filter.get("events", []))
    with pg_client.PostgresClient() as cur:
        query = cur.mogrify("""\
            INSERT INTO public.funnels (project_id, user_id, name, filter,is_public) 
            VALUES (%(project_id)s, %(user_id)s, %(name)s, %(filter)s::jsonb,%(is_public)s)
            RETURNING *;""",
                            {"user_id": user_id, "project_id": project_id, "name": name, "filter": json.dumps(filter),
                             "is_public": is_public})

        cur.execute(
            query
        )
        r = cur.fetchone()
        r["created_at"] = TimeUTC.datetime_to_timestamp(r["created_at"])
        r = helper.dict_to_camel_case(r)
        r["filter"]["startDate"], r["filter"]["endDate"] = TimeUTC.get_start_end_from_range(r["filter"]["rangeValue"])
        return {"data": r}


def update(funnel_id, user_id, name=None, filter=None, is_public=None):
    s_query = []
    if filter is not None:
        helper.delete_keys_from_dict(filter, REMOVE_KEYS)
        s_query.append("filter = %(filter)s::jsonb")
    if name is not None and len(name) > 0:
        s_query.append("name = %(name)s")
    if is_public is not None:
        s_query.append("is_public = %(is_public)s")
    if len(s_query) == 0:
        return {"errors": ["Nothing to update"]}
    with pg_client.PostgresClient() as cur:
        query = cur.mogrify(f"""\
            UPDATE public.funnels 
            SET {" , ".join(s_query)}
            WHERE funnel_id=%(funnel_id)s
            RETURNING *;""",
                            {"user_id": user_id, "funnel_id": funnel_id, "name": name,
                             "filter": json.dumps(filter) if filter is not None else None, "is_public": is_public})
        # print("--------------------")
        # print(query)
        # print("--------------------")
        cur.execute(
            query
        )
        r = cur.fetchone()
        r["created_at"] = TimeUTC.datetime_to_timestamp(r["created_at"])
        r = helper.dict_to_camel_case(r)
        r["filter"]["startDate"], r["filter"]["endDate"] = TimeUTC.get_start_end_from_range(r["filter"]["rangeValue"])
        return {"data": r}


def get_by_user(project_id, user_id, range_value=None, start_date=None, end_date=None, details=False):
    with pg_client.PostgresClient() as cur:
        team_query = """INNER JOIN
                     (
                         SELECT collaborators.user_id
                         FROM public.users AS creator
                                  INNER JOIN public.users AS collaborators USING (tenant_id)
                         WHERE creator.user_id=%(user_id)s
                     ) AS team USING (user_id)"""
        cur.execute(
            cur.mogrify(
                f"""\
                SELECT DISTINCT ON (funnels.funnel_id) funnel_id,project_id, user_id, name, created_at, deleted_at, is_public
                    {",filter" if details else ""}
                FROM public.funnels {team_query}
                WHERE project_id = %(project_id)s
                  AND funnels.deleted_at IS NULL
                  AND (funnels.user_id = %(user_id)s OR funnels.is_public);""",
                {"project_id": project_id, "user_id": user_id}
            )
        )

        rows = cur.fetchall()
        rows = helper.list_to_camel_case(rows)
        for row in rows:
            row["createdAt"] = TimeUTC.datetime_to_timestamp(row["createdAt"])
            if details:
                row["filter"]["events"] = filter_stages(row["filter"]["events"])
                get_start_end_time(filter_d=row["filter"], range_value=range_value, start_date=start_date,
                                   end_date=end_date)
                counts = sessions.search2_pg(data=row["filter"], project_id=project_id, user_id=None, count_only=True)
                row["sessionsCount"] = counts["countSessions"]
                row["usersCount"] = counts["countUsers"]
                overview = significance.get_overview(filter_d=row["filter"], project_id=project_id)
                row["stages"] = overview["stages"]
                row.pop("filter")
                row["stagesCount"] = len(row["stages"])
                # TODO: ask david to count it alone
                row["criticalIssuesCount"] = overview["criticalIssuesCount"]
                row["missedConversions"] = 0 if len(row["stages"]) < 2 \
                    else row["stages"][0]["sessionsCount"] - row["stages"][-1]["sessionsCount"]
    return rows


def get_possible_issue_types(project_id):
    return [{"type": t, "title": chalicelib.utils.helper.get_issue_title(t)} for t in
            ['click_rage', 'dead_click', 'excessive_scrolling',
             'bad_request', 'missing_resource', 'memory', 'cpu',
             'slow_resource', 'slow_page_load', 'crash', 'custom_event_error',
             'js_error']]


def get_start_end_time(filter_d, range_value, start_date, end_date):
    if start_date is not None and end_date is not None:
        filter_d["startDate"], filter_d["endDate"] = start_date, end_date
    elif range_value is not None and len(range_value) > 0:
        filter_d["rangeValue"] = range_value
        filter_d["startDate"], filter_d["endDate"] = TimeUTC.get_start_end_from_range(range_value)
    else:
        filter_d["startDate"], filter_d["endDate"] = TimeUTC.get_start_end_from_range(filter_d["rangeValue"])


def delete(project_id, funnel_id, user_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify("""\
            UPDATE public.funnels 
            SET deleted_at = timezone('utc'::text, now()) 
            WHERE project_id = %(project_id)s
              AND funnel_id = %(funnel_id)s;""",
                        {"funnel_id": funnel_id, "project_id": project_id, "user_id": user_id})
        )

    return {"data": {"state": "success"}}


def get_sessions(project_id, funnel_id, user_id, range_value=None, start_date=None, end_date=None):
    f = get(funnel_id=funnel_id, project_id=project_id)
    if f is None:
        return {"errors": ["filter not found"]}
    get_start_end_time(filter_d=f["filter"], range_value=range_value, start_date=start_date, end_date=end_date)
    return sessions.search2_pg(data=f["filter"], project_id=project_id, user_id=user_id)


def get_sessions_on_the_fly(funnel_id, project_id, user_id, data):
    data["events"] = filter_stages(data.get("events", []))
    if len(data["events"]) == 0:
        f = get(funnel_id=funnel_id, project_id=project_id)
        if f is None:
            return {"errors": ["funnel not found"]}
        get_start_end_time(filter_d=f["filter"], range_value=data.get("rangeValue", None),
                           start_date=data.get('startDate', None),
                           end_date=data.get('endDate', None))
        data = f["filter"]
    return sessions.search2_pg(data=data, project_id=project_id, user_id=user_id)


def get_top_insights(project_id, funnel_id, range_value=None, start_date=None, end_date=None):
    f = get(funnel_id=funnel_id, project_id=project_id)
    if f is None:
        return {"errors": ["filter not found"]}
    get_start_end_time(filter_d=f["filter"], range_value=range_value, start_date=start_date, end_date=end_date)
    insights, total_drop_due_to_issues = significance.get_top_insights(filter_d=f["filter"], project_id=project_id)
    insights[-1]["dropDueToIssues"] = total_drop_due_to_issues
    return {"stages": helper.list_to_camel_case(insights),
            "totalDropDueToIssues": total_drop_due_to_issues}


def get_top_insights_on_the_fly(funnel_id, project_id, data):
    data["events"] = filter_stages(data.get("events", []))
    if len(data["events"]) == 0:
        f = get(funnel_id=funnel_id, project_id=project_id)
        if f is None:
            return {"errors": ["funnel not found"]}
        get_start_end_time(filter_d=f["filter"], range_value=data.get("rangeValue", None),
                           start_date=data.get('startDate', None),
                           end_date=data.get('endDate', None))
        data = f["filter"]
    insights, total_drop_due_to_issues = significance.get_top_insights(filter_d=data, project_id=project_id)
    if len(insights) > 0:
        insights[-1]["dropDueToIssues"] = total_drop_due_to_issues
    return {"stages": helper.list_to_camel_case(insights),
            "totalDropDueToIssues": total_drop_due_to_issues}


def get_issues(project_id, funnel_id, range_value=None, start_date=None, end_date=None):
    f = get(funnel_id=funnel_id, project_id=project_id)
    if f is None:
        return {"errors": ["funnel not found"]}
    get_start_end_time(filter_d=f["filter"], range_value=range_value, start_date=start_date, end_date=end_date)
    return {"data": {
        "issues": helper.dict_to_camel_case(significance.get_issues_list(filter_d=f["filter"], project_id=project_id))
    }}


@dev.timed
def get_issues_on_the_fly(funnel_id, project_id, data):
    first_stage = data.get("firstStage")
    last_stage = data.get("lastStage")
    data["events"] = filter_stages(data.get("events", []))
    if len(data["events"]) == 0:
        f = get(funnel_id=funnel_id, project_id=project_id)
        if f is None:
            return {"errors": ["funnel not found"]}
        get_start_end_time(filter_d=f["filter"], range_value=data.get("rangeValue", None),
                           start_date=data.get('startDate', None),
                           end_date=data.get('endDate', None))
        data = f["filter"]
    return {
        "issues": helper.dict_to_camel_case(
            significance.get_issues_list(filter_d=data, project_id=project_id, first_stage=first_stage,
                                         last_stage=last_stage))}


def get(funnel_id, project_id):
    with pg_client.PostgresClient() as cur:
        cur.execute(
            cur.mogrify(
                """\
                SELECT
                  *
                FROM public.funnels
                WHERE project_id = %(project_id)s
                  AND deleted_at IS NULL
                  AND funnel_id = %(funnel_id)s;""",
                {"funnel_id": funnel_id, "project_id": project_id}
            )
        )

        f = helper.dict_to_camel_case(cur.fetchone())
    if f is None:
        return None

    f["createdAt"] = TimeUTC.datetime_to_timestamp(f["createdAt"])
    f["filter"]["events"] = filter_stages(stages=f["filter"]["events"])
    return f


@dev.timed
def search_by_issue(user_id, project_id, funnel_id, issue_id, data, range_value=None, start_date=None, end_date=None):
    if len(data.get("events", [])) == 0:
        f = get(funnel_id=funnel_id, project_id=project_id)
        if f is None:
            return {"errors": ["funnel not found"]}
        get_start_end_time(filter_d=f["filter"], range_value=range_value, start_date=data.get('startDate', start_date),
                           end_date=data.get('endDate', end_date))
        data = f["filter"]

    # insights, total_drop_due_to_issues = significance.get_top_insights(filter_d=data, project_id=project_id)
    issues = get_issues_on_the_fly(funnel_id=funnel_id, project_id=project_id, data=data).get("issues", {})
    issues = issues.get("significant", []) + issues.get("insignificant", [])
    issue = None
    for i in issues:
        if i.get("issueId", "") == issue_id:
            issue = i
            break
    return {"sessions": sessions.search2_pg(user_id=user_id, project_id=project_id, issue=issue,
                                            data=data) if issue is not None else {"total": 0, "sessions": []},
            # "stages": helper.list_to_camel_case(insights),
            # "totalDropDueToIssues": total_drop_due_to_issues,
            "issue": issue}
