"""End-to-end turn flow with a scripted model (no provider calls): interpret -> clarify -> SQL -> insight."""
import time

import pytest

from texa import answer, llm
from tests.test_compile_numbers import pytestmark  # noqa: F401  (skip when the warehouse is empty)


def candidate(**over):
    base = {"outcome": "query", "reason": "", "reply": "", "suggestions": [], "source_ids": [], "shape": "unclear",
            "selection": [], "recipe": "", "metrics": [], "recipe_alternatives": [], "recipe_stated": False, "filters": [],
            "time_range": {"kind": "none", "days": 0, "start": "", "end": ""},
            "answer_request": {"need": "describe", "ask": ""}, "language": "en"}
    return base | over


@pytest.fixture
def model(monkeypatch):
    script = {}
    calls = []

    def fake(*, name, prompt, **kw):
        calls.append((name, prompt))
        out = script[name]
        return out(prompt) if callable(out) else out

    monkeypatch.setattr(llm, "generate_structured", fake)
    monkeypatch.setattr(llm, "get_connection", lambda with_key=False: {"answer_language": "auto"})
    return script, calls


def test_breakdown_answer_with_placeholders(model):
    script, calls = model
    script["interpret"] = candidate(source_ids=["olist_marketplace"], selection=["payment_type"], recipe="revenue",
                                    time_range={"kind": "all", "days": 0, "start": "", "end": ""})
    script["insight"] = {"headline": "Credit card leads with [[f_max_revenue]].",
                         "body": ["Total revenue is [[f_total_revenue]].", "This cites [[f_made_up]] and is dropped."],
                         "caveats": [], "follow_ups": ["Revenue by month"]}
    out = answer.ask_cli("revenue by payment type for olist")
    assert out["status"] == "answered", out
    assert out["rows"][0]["payment_type"] == "credit_card"
    assert "BRL" in out["insight"]["headline"] and "[[" not in out["insight"]["headline"]
    assert len(out["insight"]["body"]) == 1  # the sentence citing an unknown fact is gone
    assert [c[0] for c in calls] == ["interpret", "insight"]


def test_asks_for_store_and_period_then_answers(model):
    script, calls = model
    script["interpret"] = candidate(recipe="buyers", selection=["event_month"])
    script["insight"] = {"headline": "Buyers peaked at [[f_peak_buyers]].", "body": [], "caveats": [], "follow_ups": []}
    out = answer.ask_cli("buyers per month")
    assert out["status"] == "needs_clarification"
    assert {f["id"] for f in out["form"]["fields"]} == {"source", "time_range"}
    out = answer.ask_cli("buyers per month", answers={"source": ["cosmetics_shop"], "time_range": ["all"]})
    assert out["status"] == "answered", out
    assert [c[0] for c in calls].count("interpret") == 2  # answering the form made no extra model call
    assert out["query_spec"]["shape"] == "time_trend"


def test_store_is_inferred_when_only_one_can_answer(model):
    script, _ = model
    script["interpret"] = candidate(recipe="late_delivery_rate", time_range={"kind": "all", "days": 0, "start": "", "end": ""})
    script["insight"] = {"headline": "[[f_late_delivery_rate]] of deliveries were late.", "body": [], "caveats": [], "follow_ups": []}
    out = answer.ask_cli("how many deliveries are late?")
    assert out["status"] == "answered", out
    assert out["query_spec"]["source_ids"] == ["olist_marketplace"]
    assert "%" in out["insight"]["headline"]


def test_value_matching_and_refusal(model):
    script, _ = model
    script["interpret"] = candidate(source_ids=["olist_marketplace"], recipe="orders",
                                    filters=[{"field": "payment_type", "operator": "=", "values_mentioned": ["Boleto"]}],
                                    time_range={"kind": "last_n_days", "days": 30, "start": "", "end": ""})
    script["insight"] = {"headline": "[[f_orders]] orders.", "body": [], "caveats": [], "follow_ups": []}
    out = answer.ask_cli("boleto orders last 30 days")
    assert out["status"] == "answered", out
    assert out["query_spec"]["filters"] == [{"field": "payment_type", "operator": "=", "values": ["boleto"]}]

    script["interpret"] = candidate(source_ids=["olist_marketplace"], recipe="add_to_carts",
                                    time_range={"kind": "all", "days": 0, "start": "", "end": ""})
    out = answer.ask_cli("add to carts on olist")
    assert out["status"] == "refused" and "does not log" in out["message"]


def test_variant_group_answers_without_asking(model):
    script, _ = model
    script["interpret"] = candidate(source_ids=["cosmetics_shop"], recipe_alternatives=["buyer_conversion_rate", "view_to_purchase_rate"],
                                    time_range={"kind": "last_n_days", "days": 30, "start": "", "end": ""})
    script["insight"] = {"headline": "Conversion is [[f_buyer_conversion_rate]].", "body": [], "caveats": [], "follow_ups": []}
    out = answer.ask_cli("conversion rate")
    assert out["status"] == "answered", out
    assert [v["id"] for v in out["variants"]] == ["buyer_conversion_rate", "view_to_purchase_rate"]


def test_unknown_ids_from_model_are_rejected(model):
    script, _ = model
    script["interpret"] = candidate(source_ids=["cosmetics_shop"], recipe="profit_margin",
                                    time_range={"kind": "all", "days": 0, "start": "", "end": ""})
    out = answer.ask_cli("profit margin")
    assert out["status"] == "error" and out["error"]["code"] == "MODEL_OUTPUT_INVALID"


def test_edit_rewinds_the_conversation(model):
    script, _ = model
    script["interpret"] = candidate(outcome="conversation", reply="Hi.")

    def settle(turn_id):
        for _ in range(100):
            if answer.RUNS[turn_id].done:
                return
            time.sleep(0.05)

    first = answer.ask("hello", None, None, None)
    settle(first["turn_id"])
    second = answer.ask("and again", first["conversation_id"], None, None)
    settle(second["turn_id"])

    dropped = answer.edit(first["turn_id"], "hello, edited")
    settle(first["turn_id"])
    assert dropped == [second["turn_id"]]
    with pytest.raises(LookupError):
        answer.load_turn(second["turn_id"])
    edited = answer.load_turn(first["turn_id"])
    assert edited["question"] == "hello, edited" and edited["status"] == "conversation"
