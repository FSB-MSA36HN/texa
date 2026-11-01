"""Opt-in PostgreSQL tests on the isolated fixture DB; model calls are scripted."""
import json
import os
import time
from copy import deepcopy

import pytest
import yaml

from texa import answer, catalog, db, llm
from texa.compile import compile_spec
from texa.pipeline import run_spec
from texa.sanity import check_availability
from texa.spec import validate_spec
from tests.test_flow import candidate

pytestmark = pytest.mark.skipif(not os.environ.get("TEXA_PRODUCT_TEST_DSN"), reason="isolated product fixture DB not configured")


@pytest.fixture
def product():
    if not db.DB_DSN.endswith("/texa_benchmark") or not db.READER_DSN.endswith("/texa_benchmark"):
        pytest.fail("product integration tests require app/reader DSNs for texa_benchmark")
    cat = catalog.published()
    assert cat.policy.max_sources == 1
    return cat, catalog.load_sources(max_age=0)


def test_nested_query_executes_against_postgresql(product):
    cat, sources = product
    out = run_spec({"source_ids": ["event_benchmark"], "recipe": "events", "shape": "breakdown",
                    "selection": ["device_type"], "time_range": {"kind": "all"}}, cat, sources)
    assert {r["device_type"]: r["events"] for r in out["rows"]} == {"mobile": 6, "desktop": 3, "tablet": 3}


def test_requested_top_k_is_preserved_when_full_result_is_rerun(product, monkeypatch):
    cat, sources = product
    spec = {"source_ids": ["event_benchmark"], "recipe": "events", "shape": "breakdown", "top_k": 2,
            "selection": ["device_type"], "time_range": {"kind": "all"}}
    out = run_spec(spec, cat, sources)
    assert [r["device_type"] for r in out["rows"]] == ["mobile", "desktop"]
    assert not out["partial"]
    monkeypatch.setattr(answer, "load_turn", lambda _: {"state": {"query_spec": out["query_spec"], "dataset_version": answer._snapshot(sources)}})
    full = answer.full_result("turn")
    assert full["rows"] == out["rows"]


def test_numeric_nested_filters_and_missing_values_on_transaction_fixture(product):
    cat, sources = deepcopy(product)
    raw = cat.model_dump()
    raw["dimensions"].append({"id": "amount", "label": "Amount", "field": "ep.checkout.amount", "cast": "number"})
    cat = catalog.validate_catalog(raw)
    sources["event_benchmark"].ep_keys.add("checkout.amount")
    raw_spec = {"source_ids": ["event_benchmark"], "contract_version": cat.contract_version, "recipe": "events",
                "shape": "aggregate", "time_range": {"kind": "all"},
                "filters": [{"field": "amount", "operator": "IN", "values": ["10.0"]}]}
    spec = validate_spec(raw_spec, cat, sources)
    compiled = compile_spec(spec, cat, check_availability(spec, cat, sources))
    # Fixture already contains a purchase with amount='10'. Numeric IN must match
    # it despite different textual formatting. Extra values are rolled back.
    with db.app_conn() as conn:
        with conn.transaction(force_rollback=True):
            for i, ep in enumerate(({}, {"checkout": {"amount": None}}, {"checkout": {"amount": "oops"}})):
                conn.execute("INSERT INTO analytics.event_activity (event_id, source_id, event_ts, event_date, event_name, user_id, first_seen_date, currency, ep) "
                             "VALUES (%s,'event_benchmark',now(),'2025-01-03','view','edge','2025-01-03','USD',%s)",
                             (f"edge-{i}", json.dumps(ep)))
            rows = conn.execute(compiled.query, compiled.params).fetchall()
            assert rows[0]["events"] == 1


def test_persisted_memory_long_noise_reference_and_reload(product, monkeypatch):
    cat, sources = product
    monkeypatch.setattr(llm, "get_connection", lambda **_: {"answer_language": "vi"})
    monkeypatch.setattr(answer.insight, "write", lambda *a, **k: {"headline": "Số liệu", "body": [], "caveats": [], "follow_ups": []})

    def interpret_question(question, previous, *a, context=None, **kw):
        if question == "Cảm ơn":
            return candidate(outcome="conversation", reply="Đã rõ", language="vi")
        if question == "Chia theo thiết bị":
            assert context["inherited_slots"]["recipe"] == "revenue"
            return candidate(recipe="revenue", source_ids=["event_benchmark"], selection=["device_type"],
                             time_range={"kind": "all"}, language="vi")
        return candidate(recipe="revenue", source_ids=["event_benchmark"], time_range={"kind": "all"}, language="vi")

    monkeypatch.setattr(answer.interpret, "interpret", interpret_question)

    def ask(question, conversation=None):
        ids = answer.ask(question, conversation, None, None)
        deadline = time.monotonic() + 5
        while not answer.RUNS[ids["turn_id"]].done:
            if time.monotonic() > deadline:
                pytest.fail("scripted query did not finish")
            time.sleep(0.01)
        turn = answer.load_turn(ids["turn_id"])
        assert turn["status"] in {"answered", "conversation"}, turn["state"]
        return ids, turn

    first, _ = ask("Doanh thu toàn bộ dữ liệu")
    try:
        for _ in range(10):
            ask("Cảm ơn", first["conversation_id"])
        last, turn = ask("Chia theo thiết bị", first["conversation_id"])
        assert turn["state"]["context"]["references"] == [first["turn_id"]]
        with db.app_conn() as conn:
            state = conn.execute("SELECT memory FROM app.conversations WHERE id=%s", (first["conversation_id"],)).fetchone()["memory"]
        assert len(state["topics"]) == 1
        slots = state["topics"][0]["slots"]
        assert slots["recipe"]["turn_id"] == first["turn_id"]
        assert slots["selection"]["turn_id"] == last["turn_id"]
        assert state["topics"][0]["result_ref"] == last["turn_id"]
    finally:
        with db.app_conn() as conn:
            conn.execute("DELETE FROM app.conversations WHERE id=%s", (first["conversation_id"],))
