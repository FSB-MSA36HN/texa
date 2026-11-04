import pytest

from texa.memory import apply_turn, select_context


def test_ordinary_followup_targets_active_query_even_if_old_question_matches_words():
    old = answered("a", "Revenue only on mobile", filters=[{"field": "device", "values": ["mobile"]}])
    active = answered("b", "Buyers for all devices", recipe="buyers")
    ctx = select_context([old, active], "Only mobile", catalog_version=3)
    assert ctx["references"] == ["b"]
    assert [t["id"] for t in ctx["turns"]] == ["b"]


def test_vietnamese_return_keeps_metric_words_for_topic_lookup():
    old = answered("a", "Doanh thu toàn bộ dữ liệu")
    active = answered("b", "Số người mua ngày hôm qua", recipe="buyers")
    ctx = select_context([old, active], "Quay lại doanh thu", catalog_version=3)
    assert ctx["references"] == ["a"]
from uuid import UUID


def answered(id_, question, **spec):
    return {"id": id_, "question": question, "status": "answered", "state": {"query_spec": {
        "contract_version": 3, "source_ids": ["shop"], "shape": "aggregate", "selection": [],
        "recipe": "revenue", "metrics": [], "filters": [], "time_range": {"kind": "all"}, **spec,
    }}}


def test_pending_clarification_does_not_overwrite_committed_slots():
    memory = apply_turn(None, answered("t1", "Revenue for Shop"), catalog_version=3)
    pending = {"id": "t2", "question": "orders?", "status": "needs_clarification",
               "state": {"candidate": {"recipe": "orders"}}}

    after = apply_turn(memory, pending, catalog_version=3)

    assert after["active_topic_id"] == "t1"
    assert after["topics"][-1]["slots"]["recipe"]["value"] == "revenue"
    assert after["pending"]["turn_id"] == "t2"


def test_distant_topic_lookup_survives_intervening_noise_without_leaking_noise_slots():
    revenue = answered("t1", "Revenue by category for shop", selection=["category"])
    noise = answered("t2", "How many orders in region West?", recipe="orders", selection=["region"],
                     filters=[{"field": "region", "operator": "=", "values": ["West"]}])

    ctx = select_context([revenue, noise], "back to revenue by category?", catalog_version=3)

    assert ctx["relation"] == "followup"
    assert ctx["references"] == ["t1"]
    assert ctx["inherited_slots"]["recipe"] == "revenue"
    assert ctx["inherited_slots"]["selection"] == ["category"]
    assert ctx["inherited_slots"]["filters"] == []


def test_new_topic_does_not_inherit_previous_slots():
    prior = answered("t1", "Revenue by category for shop", selection=["category"])

    ctx = select_context([prior], "Show orders by region for Shop", catalog_version=3)

    assert ctx["relation"] == "new_topic"
    assert ctx["inherited_slots"] == {}


def test_standalone_query_with_shared_source_does_not_retrieve_old_result():
    prior = answered("t1", "Revenue by category for shop", selection=["category"])

    ctx = select_context([prior], "Show revenue by region for Shop?", catalog_version=3)

    assert ctx["relation"] == "new_topic"
    assert ctx["turns"] == []
    assert ctx["inherited_slots"] == {}


def test_explicit_topic_switch_excludes_even_lexically_relevant_turns():
    prior = answered("t1", "Revenue by category for shop", selection=["category"])

    ctx = select_context([prior], "Different topic: revenue by category?", catalog_version=3)

    assert ctx["relation"] == "new_topic"
    assert ctx["turns"] == []
    assert ctx["inherited_slots"] == {}


def test_uuid_turn_ids_are_json_friendly():
    import json

    uid = UUID("12345678-1234-5678-1234-567812345678")
    memory = apply_turn(None, answered(uid, "Revenue for shop"), catalog_version=3)

    assert memory["topics"][0]["id"] == str(uid)
    json.dumps(memory)


def test_breakdown_prefixes_are_followups_but_complete_queries_are_fresh():
    prior = answered("t1", "Revenue by month", selection=["event_month"])

    vi = select_context([prior], "Chia theo thiết bị", catalog_version=3)
    en = select_context([prior], "Break down by device", catalog_version=3)
    complete = select_context([prior], "Revenue by device", catalog_version=3)

    assert vi["relation"] == "followup" and vi["references"] == ["t1"]
    assert en["relation"] == "followup" and en["references"] == ["t1"]
    assert complete["relation"] == "new_topic" and complete["turns"] == []


def test_explicit_new_topic_overrides_ambiguous_explanation():
    history = [answered("t1", "Revenue by month", selection=["month"]),
               answered("t2", "Orders by region", recipe="orders", selection=["region"])]

    ctx = select_context(history, "Different topic: why are orders higher?", catalog_version=3)

    assert ctx["relation"] == "new_topic"
    assert ctx["clarification_needed"] is False
    assert ctx["turns"] == []


def test_explicit_return_with_multiple_equal_matches_asks_which_result():
    history = [answered("t1", "Revenue by month", selection=["month"]),
               answered("t2", "Revenue by category", selection=["category"])]

    ctx = select_context(history, "Back to revenue", catalog_version=3)

    assert ctx["relation"] == "ambiguous"
    assert ctx["clarification_needed"] is True
    assert set(ctx["references"]) == {"t1", "t2"}


def test_detailed_explanation_uses_only_available_prior_result():
    prior = answered("t1", "Revenue by month", selection=["month"])

    ctx = select_context([prior], "Why was revenue lower?", catalog_version=3)

    assert ctx["relation"] == "followup"
    assert ctx["references"] == ["t1"]
    assert ctx["clarification_needed"] is False


def test_ambiguous_why_does_not_bind_to_nearest_of_multiple_results():
    history = [
        answered("t1", "Revenue by month for shop", selection=["month"]),
        answered("t2", "Orders by category for shop", recipe="orders", selection=["category"]),
    ]

    ctx = select_context(history, "Why?", catalog_version=3)

    assert ctx["relation"] == "ambiguous"
    assert ctx["clarification_needed"] is True
    assert ctx["inherited_slots"] == {}


def test_catalog_version_change_clears_old_topics():
    memory = apply_turn(None, answered("t1", "Revenue for shop"), catalog_version=3)

    changed = apply_turn(memory, answered("t2", "Orders for shop", recipe="orders"), catalog_version=4)

    assert [t["id"] for t in changed["topics"]] == ["t2"]
    assert changed["catalog_version"] == 4


def test_more_than_ten_intervening_turns_can_retrieve_an_older_topic():
    revenue = answered("t1", "Revenue by category for shop", selection=["category"])
    noise = [answered(f"n{i}", f"Orders by region{ i }", recipe="orders", selection=[f"region{i}"])
             for i in range(12)]

    ctx = select_context([revenue, *noise], "back to revenue by category", catalog_version=3)

    assert ctx["relation"] == "followup"
    assert ctx["references"] == ["t1"]
    assert ctx["inherited_slots"]["selection"] == ["category"]


def test_vietnamese_followup_cues_are_accent_insensitive_and_question_mark_is_not_a_cue():
    prior = answered("t1", "Doanh thu theo danh mục", selection=["category"])

    followup = select_context([prior], "Còn theo tháng thì sao?", catalog_version=3)
    unrelated = select_context([prior], "Hiển thị orders theo vùng?", catalog_version=3)

    assert followup["relation"] == "followup"
    assert unrelated["relation"] == "new_topic"
    assert unrelated["inherited_slots"] == {}


def test_non_answered_turns_do_not_become_topics_or_result_references():
    good = answered("t1", "Revenue by month", selection=["month"])
    failed = {"id": "t2", "question": "Revenue by region", "status": "error",
              "state": {"query_spec": {"recipe": "revenue", "selection": ["region"]}}}
    clarification = {"id": "t3", "question": "Revenue by city?", "status": "needs_clarification",
                     "state": {"candidate": {"recipe": "revenue"}}}

    ctx = select_context([good, failed, clarification], "Why?", catalog_version=3)

    assert ctx["references"] == ["t1"]
    assert ctx["inherited_slots"]["selection"] == ["month"]


def test_ambiguous_explanation_offers_all_answered_references_when_no_match():
    history = [answered("t1", "Revenue by month", selection=["month"]),
               answered("t2", "Orders by region", recipe="orders", selection=["region"])]

    ctx = select_context(history, "Why?", catalog_version=3)

    assert ctx["relation"] == "ambiguous"
    assert set(ctx["references"]) == {"t1", "t2"}


def test_followup_correction_updates_changed_slot_and_preserves_other_slot_provenance():
    first = answered("t1", "Revenue by category", selection=["category"])
    memory = apply_turn(None, first, catalog_version=3)
    context = {"relation": "followup", "references": ["t1"]}
    correction = answered("t2", "Actually revenue by region", selection=["region"])

    updated = apply_turn(memory, correction, catalog_version=3, context=context)
    topic = updated["topics"][0]

    assert len(updated["topics"]) == 1
    assert topic["id"] == "t1"
    assert topic["result_ref"] == "t2"
    assert topic["slots"]["recipe"]["turn_id"] == "t1"
    assert topic["slots"]["selection"]["value"] == ["region"]
    assert topic["slots"]["selection"]["turn_id"] == "t2"


def test_new_question_with_question_mark_and_max_turns_zero():
    prior = answered("t1", "Revenue by category", selection=["category"])

    ctx = select_context([prior], "Show orders by region?", catalog_version=3, max_turns=0)

    assert ctx["relation"] == "new_topic"
    assert ctx["turns"] == []
    assert ctx["inherited_slots"] == {}


@pytest.mark.parametrize("question", [
    "Chỉ thêm điều kiện mobile vào kết quả đó.",
    "Add a mobile filter to that result.",
])
def test_result_modification_resolves_across_social_noise(question):
    prior = answered("t1", "Revenue on 2025-01-31")
    noise = {"id": "t2", "question": "Cảm ơn, bạn giải thích rõ rồi.", "status": "conversation", "state": {}}

    ctx = select_context([prior, noise], question, catalog_version=3)

    assert ctx["relation"] == "followup"
    assert ctx["references"] == ["t1"]
    assert ctx["inherited_slots"]["recipe"] == "revenue"


def test_explicit_new_topic_overrides_result_anaphora_and_ordinal():
    prior = answered("t1", "Revenue by month", selection=["month"])
    later = answered("t2", "Orders by region", recipe="orders", selection=["region"])

    ctx = select_context([prior, later], "Different topic: go back to the first result", catalog_version=3)

    assert ctx["relation"] == "new_topic"
    assert ctx["references"] == []
    assert ctx["inherited_slots"] == {}
    assert ctx["clarification_needed"] is False


@pytest.mark.parametrize(("question", "expected"), [
    ("Quay lại kết quả đầu", "t1"),
    ("Go back to result number 2", "t2"),
])
def test_first_and_numbered_results_resolve_across_social_noise(question, expected):
    first = answered("t1", "Revenue by month", selection=["month"])
    noise = {"id": "t-noise", "question": "Chào bạn", "status": "conversation", "state": {}}
    second = answered("t2", "Orders by region", recipe="orders", selection=["region"])

    ctx = select_context([first, noise, second], question, catalog_version=3)

    assert ctx["relation"] == "followup"
    assert ctx["references"] == [expected]
    assert ctx["inherited_slots"]["recipe"] == ("revenue" if expected == "t1" else "orders")


def test_question_ordinal_counts_non_answer_turns_without_shifting_to_next_result():
    first = answered("t1", "Revenue by month", selection=["month"])
    social = {"id": "t2", "question": "Chào bạn", "status": "conversation", "state": {}}
    third = answered("t3", "Orders by region", recipe="orders", selection=["region"])

    ctx = select_context([first, social, third], "Return to question number 2", catalog_version=3)

    assert ctx["relation"] == "ambiguous"
    assert ctx["clarification_needed"] is True
    assert ctx["inherited_slots"] == {}


def test_question_ordinal_uses_raw_history_when_stale_result_was_filtered():
    stale = answered("t1", "Revenue by month", selection=["month"])
    current = answered("t2", "Orders by region", recipe="orders", selection=["region"])
    ordinal_history = [stale, current]
    current_history = [current]

    first = select_context(current_history, "Return to the first question", catalog_version=3,
                           ordinal_history=ordinal_history)
    second = select_context(current_history, "Return to question number 2", catalog_version=3,
                            ordinal_history=ordinal_history)

    assert first["relation"] == "ambiguous"
    assert first["clarification_needed"] is True
    assert first["inherited_slots"] == {}
    assert second["relation"] == "followup"
    assert second["references"] == ["t2"]
    assert second["inherited_slots"]["recipe"] == "orders"


@pytest.mark.parametrize("question", ["Return to result number 3", "Go back to question number 9"])
def test_unavailable_or_out_of_range_ordinal_never_inherits(question):
    first = answered("t1", "Revenue by month", selection=["month"])

    ctx = select_context([first], question, catalog_version=3)

    assert ctx["relation"] == "ambiguous"
    assert ctx["clarification_needed"] is True
    assert ctx["inherited_slots"] == {}


def test_generic_return_remains_ambiguous_with_multiple_matching_results():
    first = answered("t1", "Revenue by month", selection=["month"])
    second = answered("t2", "Revenue by category", selection=["category"])

    ctx = select_context([first, second], "Go back to revenue", catalog_version=3)

    assert ctx["relation"] == "ambiguous"
    assert ctx["clarification_needed"] is True
    assert set(ctx["references"]) == {"t1", "t2"}
    assert ctx["inherited_slots"] == {}


def test_multiple_explicit_ordinals_do_not_silently_choose_first_reference():
    first = answered("t1", "Revenue by month", selection=["month"])
    second = answered("t2", "Orders by region", recipe="orders", selection=["region"])

    ctx = select_context([first, second], "Compare question 1 and question 2", catalog_version=3)

    assert ctx["relation"] == "ambiguous"
    assert ctx["clarification_needed"] is True
    assert ctx["inherited_slots"] == {}
