"""Opt-in PostgreSQL checks for the ablation variants; every LLM call is scripted."""
import os
import time

import pytest

from texa import ablation, answer, db, llm
from tests.test_flow import candidate


pytestmark = pytest.mark.skipif(os.environ.get("TEXA_ABLATION_TEST_DSN") != "1",
                                reason="set TEXA_ABLATION_TEST_DSN=1 on an isolated fixture DB")


@pytest.fixture(autouse=True)
def isolated_benchmark_db(monkeypatch):
    if (not db.DB_DSN.endswith("/texa_benchmark") or
            not db.READER_DSN.endswith("/texa_benchmark")):
        pytest.fail("ablation integration requires app and reader DSNs for texa_benchmark")
    if not os.environ.get("TEXA_PRODUCT_TEST_DSN"):
        pytest.fail("also set TEXA_PRODUCT_TEST_DSN=1 to enable the established product test contract")
    monkeypatch.setattr(llm, "get_connection", lambda **_: {"answer_language": "vi"})
    monkeypatch.setattr(answer.insight, "write", lambda *a, **k: {
        "headline": "Kết quả kiểm thử", "body": [], "caveats": [], "follow_ups": []})
    original_ask = answer.ask
    conversations = set()

    def tracked_ask(question, conversation_id=None, model=None, scope=None):
        result = original_ask(question, conversation_id, model, scope)
        conversations.add(result["conversation_id"])
        return result

    monkeypatch.setattr(answer, "ask", tracked_ask)
    yield
    if conversations:
        with db.app_conn() as conn:
            conn.execute("DELETE FROM app.conversations WHERE id = ANY(%s::uuid[])", (list(conversations),))


def _run(turn_id, expected=None, timeout=8):
    deadline = time.monotonic() + timeout
    while not answer.RUNS[turn_id].done:
        if time.monotonic() >= deadline:
            pytest.fail("scripted ablation turn timed out")
        time.sleep(0.01)
    turn = answer.load_turn(turn_id)
    if expected is not None:
        assert turn["status"] == expected, turn["state"]
    return turn


def _ask(question, conversation_id=None):
    return answer.ask(question, conversation_id, "scripted-test-model", None)


def _candidate_for(question):
    # A deliberately absent period makes F ask, and gives C0 a constrained
    # choice among the resolver's actual period options.
    all_time = "toàn bộ dữ liệu" in question.lower()
    period = ({"kind": "all", "days": 0, "start": "", "end": ""} if all_time else
              {"kind": "none", "days": 0, "start": "", "end": ""})
    selection = [] if all_time else ["event_date"]
    return candidate(source_ids=["event_benchmark"], recipe="revenue", selection=selection,
                     time_range=period,
                     language="vi")


def test_f_asks_then_runs_real_resolver_compiler_and_full_result(monkeypatch):
    monkeypatch.setenv("TEXA_ABLATION_VARIANT", "F")
    monkeypatch.delenv("TEXA_MEMORY_MODE", raising=False)
    calls = []

    def scripted(*, name, **kwargs):
        calls.append(name)
        if name == "interpret":
            return _candidate_for("Doanh thu mua hàng theo ngày")
        pytest.fail(f"unexpected LLM call: {name}")

    monkeypatch.setattr(llm, "generate_structured", scripted)
    ids = _ask("Doanh thu mua hàng theo ngày")
    pending = _run(ids["turn_id"], "needs_clarification")
    assert [field["id"] for field in pending["state"]["form"]["fields"]] == ["time_range"]
    assert pending["state"]["ablation"]["variant"] == "F"
    assert pending["state"]["ablation"]["clarification_requested"] is True
    answer.answer_clarification(ids["turn_id"], {"time_range": ["last_7"]})
    completed = _run(ids["turn_id"], "answered")
    assert calls == ["interpret"]  # form answers do not cause another model call
    assert completed["state"]["ablation"]["variant"] == "F"
    assert completed["state"]["query_spec"]["time_range"]["kind"] == "last_n_days"
    assert completed["state"]["query_spec"]["time_range"]["days"] == 7
    full = answer.full_result(ids["turn_id"])
    assert full["partial"] is False
    assert full["rows"] == completed["state"]["rows"]
    with db.app_conn() as conn:
        conn.execute("DELETE FROM app.conversations WHERE id=%s", (ids["conversation_id"],))


def test_c0_selects_only_offered_period_and_uses_the_same_real_query_path(monkeypatch):
    monkeypatch.setenv("TEXA_ABLATION_VARIANT", "C0")
    monkeypatch.delenv("TEXA_MEMORY_MODE", raising=False)
    calls = []

    def scripted(*, name, **kwargs):
        calls.append((name, kwargs))
        if name == "interpret":
            return _candidate_for("Doanh thu mua hàng theo ngày")
        if name == "ablation_guess":
            assert kwargs["model"] == "scripted-test-model"
            assert "last_7" in kwargs["prompt"]
            assert "gold" not in kwargs["prompt"].lower()
            return {"choice_id": "last_7"}
        pytest.fail(f"unexpected LLM call: {name}")

    monkeypatch.setattr(llm, "generate_structured", scripted)
    ids = _ask("Doanh thu mua hàng theo ngày")
    completed = _run(ids["turn_id"], "answered")
    assert [name for name, _ in calls] == ["interpret", "ablation_guess"]
    assert completed["state"]["ablation"]["variant"] == "C0"
    assert completed["state"]["ablation"]["clarification_requested"] is True
    assert completed["state"]["ablation"]["clarification_eligible"] is True
    assert completed["state"]["ablation"]["clarification_invoked"] is True
    assert completed["state"]["ablation"]["clarification_choice_id"] == "last_7"
    assert completed["state"]["query_spec"]["time_range"]["kind"] == "last_n_days"
    assert completed["state"]["query_spec"]["time_range"]["days"] == 7
    full = answer.full_result(ids["turn_id"])
    assert full["rows"] == completed["state"]["rows"]
    with db.app_conn() as conn:
        conn.execute("DELETE FROM app.conversations WHERE id=%s", (ids["conversation_id"],))


def test_m0_does_not_use_prior_result_or_read_history(monkeypatch):
    # Seed a valid result in the same conversation, then run a no-memory turn.
    monkeypatch.setenv("TEXA_ABLATION_VARIANT", "F")
    monkeypatch.delenv("TEXA_MEMORY_MODE", raising=False)
    monkeypatch.setattr(llm, "generate_structured", lambda **kw: _candidate_for(kw.get("prompt", "")))
    seed = _ask("Doanh thu toàn bộ dữ liệu")
    first = _run(seed["turn_id"], "answered")

    monkeypatch.setenv("TEXA_ABLATION_VARIANT", "M0")
    history_calls = []

    def interpret(*, prompt, **kwargs):
        history_calls.append(prompt)
        return candidate(outcome="answer_from_previous", answer_request={"need": "explain", "ask": "why"}, language="vi")

    monkeypatch.setattr(llm, "generate_structured", interpret)
    # Observe absence of DB history reads on the M0 turn itself.
    original_history = answer._history
    monkeypatch.setattr(answer, "_history", lambda *a, **k: pytest.fail("M0 read conversation history"))
    second = _ask("Vì sao doanh thu như vậy?", seed["conversation_id"])
    refused = _run(second["turn_id"], "refused")
    assert first["status"] == "answered"
    assert refused["state"]["ablation"]["variant"] == "M0"
    assert refused["state"].get("based_on") is None
    assert history_calls
    assert answer._earlier_questions(second["turn_id"]) == []
    monkeypatch.setattr(answer, "_history", original_history)
    with db.app_conn() as conn:
        conn.execute("DELETE FROM app.conversations WHERE id=%s", (seed["conversation_id"],))


def test_m6_conversation_rollout_is_bounded_to_six_prior_turns(monkeypatch):
    monkeypatch.setenv("TEXA_ABLATION_VARIANT", "M6")
    monkeypatch.delenv("TEXA_MEMORY_MODE", raising=False)
    monkeypatch.setattr(llm, "generate_structured", lambda **kw: _candidate_for(kw.get("prompt", "")))
    first = _ask("Doanh thu toàn bộ dữ liệu")
    _run(first["turn_id"], "answered")
    conversation_id = first["conversation_id"]
    for idx in range(8):
        ids = _ask(f"Doanh thu toàn bộ dữ liệu lần {idx + 2}", conversation_id)
        turn = _run(ids["turn_id"], "answered")
        assert turn["state"]["ablation"]["variant"] == "M6"

    seen = {}

    def capture(*, name, prompt, **kwargs):
        if name != "interpret":
            pytest.fail(f"unexpected LLM call: {name}")
        seen["prompt"] = prompt
        return candidate(outcome="conversation", reply="Đã rõ", suggestions=[], language="vi")

    monkeypatch.setattr(llm, "generate_structured", capture)
    last = _ask("Cảm ơn", conversation_id)
    turn = _run(last["turn_id"], "conversation")
    assert turn["state"]["context"]["relation"] == "window6"
    assert len(turn["state"]["context"]["questions"]) == 6
    assert len(seen["prompt"].split("TURN ")) <= 7  # six history turns, plus no seventh
    with db.app_conn() as conn:
        conn.execute("DELETE FROM app.conversations WHERE id=%s", (conversation_id,))
