"""Integration tests for /api/api and /api/list endpoints."""

from __future__ import annotations

import json
import re


async def test_api_is_public_and_valid_openapi(app):
    client = app.test_client()
    response = await client.get("/api/api")
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    assert "Cache-Control" in response.headers
    assert "max-age=300" in response.headers["Cache-Control"]

    body = await response.get_json()
    assert re.match(r"^3\.", body["openapi"]), body["openapi"]
    # /api/list and /api/api must appear in the served document.
    assert "/api/list" in body["paths"]
    assert "/api/api" in body["paths"]


async def test_api_document_advertises_pydantic_schemas(app):
    """The /api document must surface our Pydantic models so external
    integrators can see request and response shapes. See SPEC section 9.9."""
    client = app.test_client()
    response = await client.get("/api/api")
    body = await response.get_json()

    components = body.get("components", {}).get("schemas", {})
    # The full ResponseOption discriminated union must be reachable from
    # /api/list via ListResponse -> Question -> response_option.
    assert "Question" in components, components.keys()
    assert "VoteOption" in components
    assert "LazyConsensusOption" in components
    assert "FreeTextOption" in components

    list_responses = body["paths"]["/api/list"]["get"]["responses"]
    # 200 references ListResponse (inlined or via $ref both acceptable).
    schema_200 = list_responses["200"]["content"]["application/json"]["schema"]
    assert schema_200.get("title") == "ListResponse" or "ListResponse" in str(schema_200)
    # 401 references our error model.
    schema_401 = list_responses["401"]["content"]["application/json"]["schema"]
    assert schema_401.get("title") == "AuthenticationRequired" or "AuthenticationRequired" in str(
        schema_401
    )


async def test_list_unauthenticated_returns_401_json(app):
    client = app.test_client()
    response = await client.get("/api/list", headers={"Accept": "application/json"})
    assert response.status_code == 401
    body = await response.get_json()
    assert body["error"] == "authentication_required"
    assert "login_url" in body


async def test_list_unauthenticated_html_redirects_to_oauth(app):
    client = app.test_client()
    response = await client.get("/api/list", headers={"Accept": "text/html"})
    assert response.status_code in (301, 302, 303, 307, 308)
    assert "/api/auth" in response.headers.get("Location", "")


async def test_list_returns_seeded_questions_for_authenticated_user(
    app, stub_session, seed_questions
):
    seed_questions(app, count=2)
    client = app.test_client()
    response = await client.get("/api/list", headers={"Accept": "application/json"})
    assert response.status_code == 200
    body = await response.get_json()
    assert body["user"] == "alice"
    assert len(body["pending"]) == 2
    first = body["pending"][0]
    assert first["project_id"] == "seapony"
    assert first["status"] == "open"
    # viewer_is_binding flips true because the seeded user is on 'seapony'.
    assert first["viewer_is_binding"] is True
    # time_remaining_seconds is server-stamped and positive (closes_at in
    # the future per the fixture).
    assert first["time_remaining_seconds"] > 0


async def test_list_filters_private_question_caller_cannot_see(app, stub_session, seed_questions):
    # Public question on seapony (visible) + private question on a project
    # the user is not on (invisible).
    seed_questions(app, count=1, project_id="seapony", is_private=0)
    seed_questions(app, count=1, project_id="infra", is_private=1, request_id="req_secret")

    client = app.test_client()
    response = await client.get("/api/list", headers={"Accept": "application/json"})
    body = await response.get_json()
    project_ids = {q["project_id"] for q in body["pending"]}
    assert project_ids == {"seapony"}


async def test_list_omits_resolved_and_removed_questions(app, stub_session, seed_questions):
    seed_questions(app, count=1, status="open")
    seed_questions(
        app,
        count=1,
        status="resolved",
        outcome="approved",
        request_id="resolved_req",
    )
    seed_questions(
        app,
        count=1,
        status="removed",
        outcome="withdrawn",
        request_id="removed_req",
    )

    client = app.test_client()
    response = await client.get("/api/list", headers={"Accept": "application/json"})
    body = await response.get_json()
    statuses = {q["status"] for q in body["pending"]}
    assert statuses == {"open"}


async def test_list_returns_empty_array_not_null(app, stub_session):
    client = app.test_client()
    response = await client.get("/api/list", headers={"Accept": "application/json"})
    body = await response.get_json()
    assert body["pending"] == []
    assert isinstance(body["pending"], list)
    assert body["recent"] == []
    assert isinstance(body["recent"], list)


async def test_list_recent_includes_resolved_and_removed_within_window(
    app, stub_session, seed_questions
):
    """SPEC §9.1: `recent` surfaces non-open questions updated in the last 14 days."""
    from datetime import UTC, datetime, timedelta

    def _iso(dt):
        return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    now = datetime.now(UTC)
    fresh = _iso(now - timedelta(days=2))
    stale = _iso(now - timedelta(days=20))

    [open_id] = seed_questions(app, count=1, status="open", request_id="open_req")
    [resolved_id] = seed_questions(
        app,
        count=1,
        status="resolved",
        outcome="approved",
        request_id="resolved_req",
        updated_at=fresh,
    )
    [removed_id] = seed_questions(
        app,
        count=1,
        status="removed",
        outcome="withdrawn",
        request_id="removed_req",
        updated_at=fresh,
    )
    [ancient_id] = seed_questions(
        app,
        count=1,
        status="resolved",
        outcome="approved",
        request_id="ancient_req",
        updated_at=stale,
    )

    client = app.test_client()
    response = await client.get("/api/list", headers={"Accept": "application/json"})
    assert response.status_code == 200
    body = await response.get_json()

    # `pending` still contains only open questions.
    pending_ids = {q["question_id"] for q in body["pending"]}
    assert pending_ids == {open_id}

    # `recent` carries the open + the two fresh-but-closed questions, but
    # not the 20-day-old one.
    recent_ids = {q["question_id"] for q in body["recent"]}
    assert open_id in recent_ids
    assert resolved_id in recent_ids
    assert removed_id in recent_ids
    assert ancient_id not in recent_ids

    # Status markers are carried per row so the UI can render an
    # "open vs closed" indicator without a per-id round trip.
    by_id = {q["question_id"]: q for q in body["recent"]}
    assert by_id[open_id]["status"] == "open"
    assert by_id[resolved_id]["status"] == "resolved"
    assert by_id[resolved_id]["outcome"] == "approved"
    assert by_id[removed_id]["status"] == "removed"
    assert by_id[removed_id]["outcome"] == "withdrawn"


async def test_list_flags_questions_the_caller_already_answered(
    app, stub_session, seed_questions, seed_response
):
    """SPEC §8.3: `viewer_has_responded` is per caller, on both arrays."""
    [answered_id] = seed_questions(app, count=1, request_id="answered_req")
    [untouched_id] = seed_questions(app, count=1, request_id="untouched_req")
    seed_response(app, question_id=answered_id, voter="alice", value="+1")

    client = app.test_client()
    response = await client.get("/api/list", headers={"Accept": "application/json"})
    assert response.status_code == 200
    body = await response.get_json()

    pending = {q["question_id"]: q for q in body["pending"]}
    assert pending[answered_id]["viewer_has_responded"] is True
    assert pending[untouched_id]["viewer_has_responded"] is False

    recent = {q["question_id"]: q for q in body["recent"]}
    assert recent[answered_id]["viewer_has_responded"] is True
    assert recent[untouched_id]["viewer_has_responded"] is False


async def test_list_viewer_has_responded_ignores_other_voters(
    app, stub_session, seed_questions, seed_response
):
    """Somebody else's vote must not mark the question as answered by us."""
    [question_id] = seed_questions(app, count=1)
    seed_response(app, question_id=question_id, voter="bob", value="+1")

    client = app.test_client()
    body = await (await client.get("/api/list", headers={"Accept": "application/json"})).get_json()
    assert body["pending"][0]["viewer_has_responded"] is False


async def test_list_viewer_has_responded_survives_an_amendment(
    app, stub_session, seed_questions, seed_response
):
    """Responses are append-only (§7.2), so a second row keeps the flag True."""
    [question_id] = seed_questions(app, count=1)
    seed_response(app, question_id=question_id, voter="alice", value="+1")
    seed_response(app, question_id=question_id, voter="alice", value="-1")

    client = app.test_client()
    body = await (await client.get("/api/list", headers={"Accept": "application/json"})).get_json()
    assert body["pending"][0]["viewer_has_responded"] is True


async def test_question_detail_reports_viewer_has_responded(
    app, stub_session, seed_questions, seed_response
):
    [question_id] = seed_questions(app, count=1)
    client = app.test_client()

    before = await (
        await client.get(f"/api/question/{question_id}", headers={"Accept": "application/json"})
    ).get_json()
    assert before["question"]["viewer_has_responded"] is False

    seed_response(app, question_id=question_id, voter="alice", value="+1")
    after = await (
        await client.get(f"/api/question/{question_id}", headers={"Accept": "application/json"})
    ).get_json()
    assert after["question"]["viewer_has_responded"] is True


async def test_question_detail_viewer_has_responded_false_for_anonymous(
    app, seed_questions, seed_response
):
    """No session means no responses to match, whoever else has voted."""
    [question_id] = seed_questions(app, count=1)
    seed_response(app, question_id=question_id, voter="alice", value="+1")

    client = app.test_client()
    body = await (
        await client.get(f"/api/question/{question_id}", headers={"Accept": "application/json"})
    ).get_json()
    assert body["question"]["viewer_has_responded"] is False


async def test_publist_is_public_and_excludes_private(app, seed_questions):
    """SPEC §9.13: /api/publist must be reachable without auth and must
    omit every is_private=1 row regardless of status."""
    from datetime import UTC, datetime, timedelta

    def _iso(dt):
        return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    fresh = _iso(datetime.now(UTC) - timedelta(days=1))

    [open_pub] = seed_questions(app, count=1, status="open", request_id="open_pub")
    [open_priv] = seed_questions(app, count=1, status="open", is_private=1, request_id="open_priv")
    [resolved_pub] = seed_questions(
        app,
        count=1,
        status="resolved",
        outcome="approved",
        request_id="resolved_pub",
        updated_at=fresh,
    )
    [resolved_priv] = seed_questions(
        app,
        count=1,
        status="resolved",
        outcome="approved",
        is_private=1,
        request_id="resolved_priv",
        updated_at=fresh,
    )

    client = app.test_client()
    response = await client.get("/api/publist")
    assert response.status_code == 200
    body = await response.get_json()
    ids = {q["question_id"] for q in body["questions"]}
    assert open_pub in ids
    assert resolved_pub in ids
    # Both private rows must be filtered out even though one is still open.
    assert open_priv not in ids
    assert resolved_priv not in ids


async def test_publist_excludes_closed_outside_14d_window(app, seed_questions):
    from datetime import UTC, datetime, timedelta

    def _iso(dt):
        return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    stale = _iso(datetime.now(UTC) - timedelta(days=30))
    [open_pub] = seed_questions(app, count=1, status="open", request_id="open_pub_a")
    [ancient_pub] = seed_questions(
        app,
        count=1,
        status="resolved",
        outcome="approved",
        request_id="ancient_pub",
        updated_at=stale,
    )

    client = app.test_client()
    response = await client.get("/api/publist")
    body = await response.get_json()
    ids = {q["question_id"] for q in body["questions"]}
    assert open_pub in ids
    assert ancient_pub not in ids


async def test_publist_no_auth_required(app):
    """Anonymous (no stub_session) callers must still get a 200."""
    client = app.test_client()
    response = await client.get("/api/publist", headers={"Accept": "application/json"})
    assert response.status_code == 200
    body = await response.get_json()
    assert body == {"questions": []}


async def test_publist_viewer_is_binding_is_false_for_anonymous(app, seed_questions):
    """No session means no membership, so every row reports
    viewer_is_binding=False even under binding_scope='project'."""
    seed_questions(app, count=1, status="open", binding_scope="project")
    client = app.test_client()
    response = await client.get("/api/publist")
    body = await response.get_json()
    assert body["questions"]
    assert all(q["viewer_is_binding"] is False for q in body["questions"])
    # Same reasoning for viewer_has_responded: an anonymous caller has no
    # responses of their own to match against (SPEC §8.3).
    assert all(q["viewer_has_responded"] is False for q in body["questions"])


# ---------------------------------------------------------------------------
# /api/publist caching (SPEC §9.13)
# ---------------------------------------------------------------------------


async def test_publist_caches_within_ttl(app, seed_questions, monkeypatch):
    """A second call within the TTL must return the cached body even if
    the underlying table grows between the two requests."""
    import cap_backend.routes.questions as routes

    fake_clock = {"now": 1000.0}
    monkeypatch.setattr(routes.time, "monotonic", lambda: fake_clock["now"])

    seed_questions(app, count=1, status="open", request_id="cache_first")
    client = app.test_client()
    first = await client.get("/api/publist")
    first_body = await first.get_json()
    first_ids = {q["question_id"] for q in first_body["questions"]}
    assert len(first_ids) == 1
    assert first.headers["Cache-Control"] == "public, max-age=30"

    # Insert a new row that *would* be visible if the handler refreshed.
    seed_questions(app, count=1, status="open", request_id="cache_second")

    # Advance only 5 seconds — well within the default 30s TTL — and
    # confirm the cached body is served unchanged.
    fake_clock["now"] += 5
    second = await client.get("/api/publist")
    second_body = await second.get_json()
    assert {q["question_id"] for q in second_body["questions"]} == first_ids


async def test_publist_refreshes_after_ttl(app, seed_questions, monkeypatch):
    """Crossing the TTL boundary must trigger a refresh."""
    import cap_backend.routes.questions as routes

    fake_clock = {"now": 1000.0}
    monkeypatch.setattr(routes.time, "monotonic", lambda: fake_clock["now"])

    seed_questions(app, count=1, status="open", request_id="ttl_first")
    client = app.test_client()
    await client.get("/api/publist")
    seed_questions(app, count=1, status="open", request_id="ttl_second")

    # Jump past the default 30s TTL.
    fake_clock["now"] += 31
    refreshed = await client.get("/api/publist")
    body = await refreshed.get_json()
    assert len({q["question_id"] for q in body["questions"]}) == 2


async def test_publist_ttl_zero_disables_cache(app, settings, seed_questions):
    """settings.server.publist_cache_seconds == 0 must bypass the cache."""
    settings.server.publist_cache_seconds = 0
    seed_questions(app, count=1, status="open", request_id="ttl_zero_a")
    client = app.test_client()
    first = await client.get("/api/publist")
    first_body = await first.get_json()
    assert len(first_body["questions"]) == 1
    assert first.headers["Cache-Control"] == "no-store"

    seed_questions(app, count=1, status="open", request_id="ttl_zero_b")
    second = await client.get("/api/publist")
    second_body = await second.get_json()
    assert len(second_body["questions"]) == 2


async def test_publist_cache_control_reflects_configured_ttl(app, settings):
    """The Cache-Control max-age must match the configured TTL."""
    settings.server.publist_cache_seconds = 120
    client = app.test_client()
    response = await client.get("/api/publist")
    assert response.headers["Cache-Control"] == "public, max-age=120"


async def test_list_recent_respects_private_acl(app, as_user, seed_questions):
    """Private questions outside the caller's reach must not bleed into `recent`."""
    from datetime import UTC, datetime, timedelta

    from cap_backend.auth import AuthenticatedUser

    def _iso(dt):
        return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    fresh = _iso(datetime.now(UTC) - timedelta(days=1))

    as_user(AuthenticatedUser(uid="outsider", committees=("other",)))
    [hidden_id] = seed_questions(
        app,
        count=1,
        project_id="seapony",
        is_private=1,
        status="resolved",
        outcome="approved",
        request_id="hidden_req",
        updated_at=fresh,
    )
    [visible_id] = seed_questions(
        app,
        count=1,
        project_id="other",
        is_private=0,
        status="resolved",
        outcome="approved",
        request_id="visible_req",
        updated_at=fresh,
    )

    client = app.test_client()
    response = await client.get("/api/list", headers={"Accept": "application/json"})
    assert response.status_code == 200
    body = await response.get_json()
    recent_ids = {q["question_id"] for q in body["recent"]}
    assert hidden_id not in recent_ids
    assert visible_id in recent_ids


async def test_api_response_is_cached_across_requests(app):
    client = app.test_client()
    r1 = await client.get("/api/api")
    r2 = await client.get("/api/api")
    assert r1.status_code == r2.status_code == 200
    assert await r1.get_data() == await r2.get_data()


async def test_api_response_includes_service_version(app):
    client = app.test_client()
    response = await client.get("/api/api")
    body = json.loads(await response.get_data())
    assert "version" in body["info"]
