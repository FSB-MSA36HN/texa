"""DB-free tests for conversational context selection and prompt rendering."""
from copy import deepcopy
import pytest

from texa import answer, interpret
from texa.progress import Progress
from texa.spec import SpecError
from tests.test_units import CAT, SOURCES


def test_full_result_rejects_changed_snapshot_before_executing(monkeypatch):
    monkeypatch.setattr(answer, "_persist_language", lambda *_: None)
    monkeypatch.setattr(answer, "load_turn", lambda _: {"state": {"query_spec": {"recipe": "revenue"}, "dataset_version": "old"}})
    monkeypatch.setattr(answer.catalog_mod, "published", lambda: CAT)
    monkeypatch.setattr(answer.catalog_mod, "load_sources", lambda **_: SOURCES)
    monkeypatch.setattr(answer, "_snapshot", lambda _: "new")
    monkeypatch.setattr(answer, "run_spec", lambda *_: pytest.fail("stale result must not execute"))
    with pytest.raises(SpecError) as error:
        answer.full_result("turn")
    assert error.value.code == "stale_data"


def test_variant_switch_rejects_changed_snapshot_before_executing(monkeypatch):
    turn = {"id": "turn", "question": "Q", "model": None,
            "state": {"query_spec": {"recipe": "revenue"}, "variants": [{"id": "buyers"}], "dataset_version": "old"}}
    monkeypatch.setattr(answer, "_persist_language", lambda *_: None)
    monkeypatch.setattr(answer, "load_turn", lambda _: turn)
    monkeypatch.setattr(answer, "_set_running", lambda _: None)
    monkeypatch.setattr(answer, "_start", lambda _, work: work(Progress()))
    monkeypatch.setattr(answer.catalog_mod, "published", lambda: CAT)
    monkeypatch.setattr(answer.catalog_mod, "load_sources", lambda **_: SOURCES)
    monkeypatch.setattr(answer, "_snapshot", lambda _: "new")
    monkeypatch.setattr(answer, "run_spec", lambda *_: pytest.fail("stale variant must not execute"))
    with pytest.raises(SpecError) as error:
        answer.switch_variant("turn", "buyers")
    assert error.value.code == "stale_data"


def turn(id_, question, recipe, *, dataset="snapshot-a", version=1, selection=None):
    return {
        "id": id_, "question": question, "status": "answered", "created_at": id_,
        "state": {"dataset_version": dataset, "query_spec": {
            "contract_version": version, "source_ids": ["cosmetics_shop"], "shape": "breakdown" if selection else "aggregate",
            "selection": selection or [], "recipe": recipe, "metrics": [], "filters": [],
            "time_range": {"kind": "all"},
        }, "insight": {"headline": f"answer {id_}"}},
    }


def candidate(outcome="query", **over):
    return {"outcome": outcome, "answer_request": {"need": "explain", "ask": "why"}, **over}


def setup_flow(monkeypatch, *, history, question="Show orders by region?", interpret_result=None, version=1):
    cat = deepcopy(CAT)
    cat.contract_version = version
    monkeypatch.setattr(answer, "_persist_language", lambda *_: None)
    monkeypatch.setattr(answer, "load_turn", lambda _: {
        "id": "current", "question": question, "conversation_id": "conversation", "model": None,
        "state": {"scope": []},
    })
    monkeypatch.setattr(answer, "_history", lambda *_: history)
    monkeypatch.setattr(answer.catalog_mod, "published", lambda: cat)
    monkeypatch.setattr(answer.catalog_mod, "load_sources", lambda **_: SOURCES)
    monkeypatch.setattr(answer.catalog_mod, "scoped_sources", lambda _cat, sources: sources)
    monkeypatch.setattr(answer, "_snapshot", lambda _: "snapshot-a")
    monkeypatch.setattr(answer.llm, "get_connection", lambda **_: {"answer_language": "auto"})
    calls = []

    def fake_interpret(q, previous, *_args, context=None, **_kwargs):
        calls.append((q, previous, deepcopy(context)))
        result = deepcopy(interpret_result or candidate())
        relation = 'social' if result['outcome'] == 'conversation' else 'new_topic'
        target = ''
        if question == 'Why?':
            relation = 'ambiguous'
        if result['outcome'] == 'answer_from_previous':
            relation, target = 'followup', 'a'
        result['dialogue'] = {'relation': relation, 'target_id': target,
                              'slots': {key: 'set' for key in answer.memory.SLOT_KEYS}}
        return result

    monkeypatch.setattr(answer.interpret, "interpret", fake_interpret)
    return calls


def test_ten_noise_turns_keep_explicitly_referenced_older_context(monkeypatch):
    old = turn("old", "Revenue by category", "revenue", selection=["item_category"])
    noise = [turn(f"noise-{i}", f"Orders in region {i}", "orders", selection=["region"])
             for i in range(10)]
    calls = setup_flow(monkeypatch, history=[old, *noise], question="Back to revenue by category",
                       interpret_result=candidate("conversation", reply="Hi", suggestions=[]))

    result = answer._question_work("current")(Progress())

    assert len(calls) == 1
    assert calls[0][1] == []
    assert calls[0][2]["registry"][0]["id"] == "old"
    assert result["status"] == "conversation"


def test_ambiguous_reference_returns_choice_form_without_model_call(monkeypatch):
    history = [turn("a", "Revenue by month", "revenue", selection=["event_month"]),
               turn("b", "Orders by region", "orders", selection=["region"])]
    calls = setup_flow(monkeypatch, history=history, question="Why?")

    result = answer._question_work("current")(Progress())

    assert len(calls) == 1
    assert result["status"] == "needs_clarification"
    choices = result["form"]["fields"][0]["choices"]
    assert {choice["id"] for choice in choices} == {"a", "b"}


def test_unique_selected_reference_is_reused_for_explanation(monkeypatch):
    old = turn("a", "Revenue by month", "revenue", selection=["event_month"])
    calls = setup_flow(monkeypatch, history=[old], question="Why was revenue lower?",
                       interpret_result=candidate("answer_from_previous"))
    # This is the second pass after the user chose the earlier-result form.
    monkeypatch.setattr(answer, "_history", lambda *_: [old])
    monkeypatch.setattr(answer.insight, "write", lambda *args, **kwargs: {"headline": "explained"})

    result = answer._question_work("current", reference_id="a")(Progress())

    assert result["status"] == "discussed"
    assert result["based_on"] == "a"
    assert calls[0][2]["references"] == ["a"]


def test_new_topic_does_not_send_old_turns_to_interpreter(monkeypatch):
    old = turn("a", "Revenue by category", "revenue", selection=["item_category"])
    calls = setup_flow(monkeypatch, history=[old], question="Show orders by region?", interpret_result=candidate())
    monkeypatch.setattr(answer, "_continue", lambda *_: {"status": "observed"})

    result = answer._question_work("current")(Progress())

    assert calls[0][1] == []
    assert calls[0][2]["relation"] == "unresolved"
    assert result["status"] == "observed"


def test_dataset_and_catalog_mismatches_are_excluded(monkeypatch):
    old_data = turn("old-data", "Revenue by category", "revenue", dataset="old-snapshot")
    old_catalog = turn("old-catalog", "Revenue by region", "revenue", version=0)
    calls = setup_flow(monkeypatch, history=[old_data, old_catalog], question="Back to revenue by region")
    monkeypatch.setattr(answer, "_continue", lambda *_: {"status": "observed"})

    answer._question_work("current")(Progress())

    assert calls[0][1] == []
    assert calls[0][2]["relation"] == "unresolved"


def test_render_previous_drops_whole_old_turn_blocks_to_fit_budget():
    turns = [
        {"id": "old", "question": "old-question-" + "x" * 80,
         "state": {"query_spec": {"recipe": "revenue"}, "insight": {"headline": "old-answer-" + "x" * 80}}},
        {"id": "middle", "question": "middle-question-" + "y" * 80,
         "state": {"query_spec": {"recipe": "orders"}, "insight": {"headline": "middle-answer-" + "y" * 80}}},
        {"id": "new", "question": "new-question-" + "z" * 80,
         "state": {"query_spec": {"recipe": "buyers"}, "insight": {"headline": "new-answer-" + "z" * 80}}},
    ]

    rendered = interpret.render_previous(turns, budget=110)

    assert "TURN middle" not in rendered
    assert "TURN old" not in rendered
    assert "TURN new" in rendered
    assert "new-question-" + "z" * 80 in rendered
    assert "reading:" in rendered and "answer: new-answer-" in rendered
