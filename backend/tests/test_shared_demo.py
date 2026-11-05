"""Unit checks for opt-in shared-demo ownership and admin access controls."""
import hashlib
import os
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import psycopg

from texa import main


_POSTGRES_TESTS = pytest.mark.skipif(
    os.getenv("TEXA_SHARED_TEST_DSN") != "1",
    reason="PostgreSQL shared-demo API tests require explicit TEXA_SHARED_TEST_DSN=1 opt-in",
)


def _verify_isolated_test_database():
    """Fail closed before TestClient enters lifespan, which mutates running turn states."""
    for dsn in (main.db.DB_DSN, main.db.READER_DSN):
        with psycopg.connect(dsn, connect_timeout=2) as conn:
            db_name = conn.execute("SELECT current_database()").fetchone()[0]
            if db_name != "texa_benchmark":
                pytest.fail(f"shared-demo API test refuses non-isolated database {db_name!r}")


def request(headers=None, session_hash="session-hash"):
    return SimpleNamespace(headers=headers or {}, state=SimpleNamespace(browser_session_hash=session_hash))


def test_admin_token_required_only_in_shared_mode(monkeypatch):
    monkeypatch.setenv("TEXA_SHARED_DEMO", "1")
    monkeypatch.setenv("TEXA_ADMIN_TOKEN", "a-strong-test-admin-token-123")
    with pytest.raises(HTTPException) as exc:
        main._require_admin(request())
    assert exc.value.status_code == 403
    main._require_admin(request({"authorization": "Bearer a-strong-test-admin-token-123"}))

    monkeypatch.setenv("TEXA_SHARED_DEMO", "0")
    main._require_admin(request())


def test_shared_session_hash_is_only_used_in_shared_mode(monkeypatch):
    req = request(session_hash="browser-a-hash")
    monkeypatch.setenv("TEXA_SHARED_DEMO", "1")
    assert main._session_hash(req) == "browser-a-hash"
    monkeypatch.setenv("TEXA_SHARED_DEMO", "0")
    assert main._session_hash(req) is None


def test_shared_demo_requires_long_admin_token(monkeypatch):
    monkeypatch.setenv("TEXA_SHARED_DEMO", "1")
    monkeypatch.setenv("TEXA_ADMIN_TOKEN", "too-short")
    with pytest.raises(RuntimeError, match="at least 24 characters"):
        main._validate_shared_demo_config()
    monkeypatch.setenv("TEXA_ADMIN_TOKEN", "a-long-enough-test-admin-token")
    main._validate_shared_demo_config()


def test_shared_bootstrap_does_not_expose_gateway_base_url(monkeypatch):
    monkeypatch.setenv("TEXA_SHARED_DEMO", "1")
    monkeypatch.setattr(main.llm, "get_connection", lambda: {
        "provider": "openai", "base_url": "https://gateway.example/v1", "default_model": "model",
        "allowed_models": ["model"], "max_output_tokens": 20, "daily_token_limit": 0,
        "answer_language": "vi", "from_env": False,
    })
    assert "base_url" not in main._bootstrap_connection()
    assert main._public_connection()["base_url"] == "https://gateway.example/v1"


def test_shared_questions_pin_default_model_while_local_mode_honors_selection(monkeypatch):
    calls = []
    monkeypatch.setattr(main.llm, "get_connection", lambda: {"default_model": "organizer-model", "allowed_models": []})
    monkeypatch.setattr(main.answer, "ask", lambda *args, **kwargs: calls.append((args, kwargs)) or {"ok": True})
    req = request()

    monkeypatch.setenv("TEXA_SHARED_DEMO", "1")
    assert main.post_question(main.AskBody(question="shared"), req) == {"ok": True}
    assert calls[-1][0][2] == "organizer-model"
    assert calls[-1][1]["owner_hash"] == "session-hash"
    with pytest.raises(main.llm.LLMError) as exc:
        main.post_question(main.AskBody(question="bypass", model="other-model"), req)
    assert exc.value.code == "BAD_MODEL"

    monkeypatch.setenv("TEXA_SHARED_DEMO", "0")
    assert main.post_question(main.AskBody(question="local", model="selected-model"), req) == {"ok": True}
    assert calls[-1][0][2] == "selected-model"
    assert calls[-1][1] == {"language": None}


@_POSTGRES_TESTS
def test_shared_demo_api_isolates_conversation_and_turn_routes(monkeypatch):
    """Two real browser cookies cannot list, read, mutate, or operate on each other's data."""
    monkeypatch.setenv("TEXA_SHARED_DEMO", "1")
    monkeypatch.setenv("TEXA_ADMIN_TOKEN", "a-long-enough-test-admin-token")
    monkeypatch.setenv("TEXA_COOKIE_SECURE", "0")
    _verify_isolated_test_database()

    with TestClient(main.app, raise_server_exceptions=False) as client_a, \
         TestClient(main.app, raise_server_exceptions=False) as client_b:
        first_a = client_a.get("/api/health")
        assert first_a.status_code == 200
        assert client_b.get("/api/health").status_code == 200
        cookie_a = client_a.cookies.get("texa_session")
        cookie_b = client_b.cookies.get("texa_session")
        assert cookie_a and cookie_b and cookie_a != cookie_b
        set_cookie = first_a.headers.get("set-cookie", "").lower()
        assert "httponly" in set_cookie and "samesite=lax" in set_cookie and "secure" not in set_cookie
        hash_a = hashlib.sha256(cookie_a.encode()).hexdigest()
        conv_id, turn_id = str(uuid.uuid4()), str(uuid.uuid4())
        with main.db.app_conn() as conn:
            conn.execute("INSERT INTO app.conversations(id,title,browser_session_hash) VALUES (%s,%s,%s)",
                         (conv_id, "privacy-test", hash_a))
            conn.execute("INSERT INTO app.turns(id,conversation_id,question,status) VALUES (%s,%s,%s,%s)",
                         (turn_id, conv_id, "privacy test", "answered"))

        try:
            assert [x["id"] for x in client_a.get("/api/conversations").json()] == [conv_id]
            assert client_a.get(f"/api/conversations/{conv_id}").status_code == 200
            assert client_a.patch(f"/api/conversations/{conv_id}", json={"title": "owner-renamed"}).status_code == 200
            assert client_a.get(f"/api/turns/{turn_id}").status_code == 200
            assert client_b.get("/api/conversations").json() == []
            assert client_b.get(f"/api/conversations/{conv_id}").status_code == 404
            assert client_b.patch(f"/api/conversations/{conv_id}", json={"title": "stolen"}).status_code == 404
            assert client_b.delete(f"/api/conversations/{conv_id}").status_code == 404
            assert client_b.post("/api/questions", json={"question": "new", "conversation_id": conv_id}).status_code == 404

            turn_routes = [
                ("get", f"/api/turns/{turn_id}", None),
                ("get", f"/api/turns/{turn_id}/stream", None),
                ("post", f"/api/turns/{turn_id}/answer", {"answers": {}}),
                ("post", f"/api/turns/{turn_id}/retry", None),
                ("post", f"/api/turns/{turn_id}/edit", {"question": "edit"}),
                ("post", f"/api/turns/{turn_id}/cancel", None),
                ("post", f"/api/turns/{turn_id}/variant", {"metric_id": "revenue"}),
                ("get", f"/api/turns/{turn_id}/full-result", None),
                ("post", f"/api/turns/{turn_id}/feedback", {"rating": "up"}),
            ]
            for method, url, body in turn_routes:
                response = getattr(client_b, method)(url, json=body) if body is not None else getattr(client_b, method)(url)
                assert response.status_code == 404, (method, url, response.text)
            assert client_b.get("/api/turns/not-a-uuid").status_code == 404
            assert client_b.get("/api/conversations/not-a-uuid").status_code == 404
        finally:
            with main.db.app_conn() as conn:
                conn.execute("DELETE FROM app.conversations WHERE id=%s", (conv_id,))


@_POSTGRES_TESTS
def test_shared_demo_admin_routes_require_bearer_token(monkeypatch):
    monkeypatch.setenv("TEXA_SHARED_DEMO", "1")
    monkeypatch.setenv("TEXA_ADMIN_TOKEN", "a-long-enough-test-admin-token")
    _verify_isolated_test_database()
    with TestClient(main.app, raise_server_exceptions=False) as client:
        assert client.get("/api/model-connection").status_code == 403
        assert client.get("/api/usage").status_code == 403
        assert client.post("/api/model-connection/discover", json={"provider": "openai"}).status_code == 403
        assert client.put("/api/model-connection", json={"provider": "openai"}).status_code == 403
        assert client.delete("/api/model-connection").status_code == 403
