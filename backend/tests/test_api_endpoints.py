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
