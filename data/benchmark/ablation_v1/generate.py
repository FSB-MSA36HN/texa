"""Generate the deterministic ablation suite from the frozen v2 event records.

Expected tables use the v2 Python reference evaluator. Gold SQL is emitted by its
declarative SQL writer. No Texa QuerySpec/compiler or model call is used.
"""
from __future__ import annotations

import importlib.util
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[2]
V2_GENERATOR = PROJECT / "data/benchmark/v2/generate.py"
spec = importlib.util.spec_from_file_location("benchmark_v2_generator", V2_GENERATOR)
v2 = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(v2)


def rows_for_v1():
    rows = v2.make_rows()
    start = date(2024, 12, 15)
    # Spread the same 96 events over 50 days so last_7 and all-time choices have
    # observably different answers. Preserve event IDs and all other attributes.
    for i, row in enumerate(rows):
        day = start + timedelta(days=i * 50 // len(rows))
        row["event_date"] = day.isoformat()
        row["event_id"] = f"ablation_v1_{i + 1:03d}"
    return rows


def where_for(metric, time_range="all", filters=None, breakdown=None):
    clauses = []
    if time_range == "last_7":
        latest = max(r["event_date"] for r in rows_for_v1())
        # Compiler semantics are event_date > max_date - 7, i.e. the seven
        # dates ending at max_date, inclusive.
        lower = date.fromisoformat(latest) - timedelta(days=6)
        clauses.append(f"event_date BETWEEN '{lower.isoformat()}' AND '{latest}'")
    elif isinstance(time_range, str) and time_range != "all":
        clauses.append(f"event_date='{time_range}'")
    elif isinstance(time_range, dict):
        clauses.append(f"event_date BETWEEN '{time_range['start']}' AND '{time_range['end']}'")
    for item in filters or []:
        field, value = next(iter(item.items()))
        clauses.append(f"{field}='{value}'")
    return metric, clauses, breakdown


def answer(question, metric, time_range="all", filters=None, breakdown=None, reference=None):
    query = where_for(metric, time_range, filters, breakdown)
    turn = {"question": question, "action": "answer",
            "state": {"metric": metric, "time_range": time_range, "filters": filters or [],
                      "breakdown": breakdown},
            "gold_sql": v2.sql(query), "expected_result": v2.evaluate(ROWS, query)}
    if reference is not None:
        turn["referenced_turn"] = reference
    return turn


ROWS = rows_for_v1()


def build_memory():
    scenarios = []

    def add(id_, split, phenomenon, turns):
        dep = max((i - t["referenced_turn"] for i, t in enumerate(turns, 1)
                   if t.get("referenced_turn")), default=0)
        scenarios.append({"id": id_, "split": split, "family": f"{split}_{phenomenon}",
                          "phenomenon": phenomenon, "cluster_id": id_,
                          "dependency_distance": dep, "turns": turns})

    for split in ("dev", "test"):
        if split == "dev":
            short_day, short_device, second_metric = "2025-01-20", "mobile", "buyers"
            correction_days, initial_channel, replacement_channel = (10, 11), "paid", "organic"
            noise_day, switch_dates, independent_day, independent_device = 15, (8, 9), 12, "mobile"
            new_topic_dates, return_metric, return_filter = (17, 18), "revenue", "device_type"
            ambiguous_dates, ambiguous_metric, ambiguous_final = (3, 4), "revenue", "buyers"
        else:
            short_day, short_device, second_metric = "2025-01-22", "desktop", "users"
            correction_days, initial_channel, replacement_channel = (24, 25), "email", "referral"
            noise_day, switch_dates, independent_day, independent_device = 27, (21, 22), 29, "tablet"
            new_topic_dates, return_metric, return_filter = (29, 30), "buyers", "users"
            ambiguous_dates, ambiguous_metric, ambiguous_final = (23, 24), "users", "events"
        first, corrected = correction_days
        switch_first, switch_second = switch_dates
        new_first, new_second = new_topic_dates
        ambiguous_first, ambiguous_second = ambiguous_dates
        add(f"{split}_short_filter", split, "short_followup", [
            answer(f"Doanh thu mua hàng ngày {short_day[-2:]}/1/2025 là bao nhiêu?", "revenue", short_day),
            answer(f"Chỉ tính thiết bị {short_device}.", "revenue", short_day,
                   [{"device_type": short_device}], reference=1),
        ])
        add(f"{split}_short_breakdown", split, "short_followup", [
            answer(f"Có bao nhiêu {'người mua' if second_metric == 'buyers' else 'người dùng'} trong toàn bộ dữ liệu?", second_metric),
            answer(f"Chia chỉ số {second_metric} đó theo kênh tiếp thị.", second_metric,
                   breakdown="campaign_channel", reference=1),
        ])
        add(f"{split}_correction_date", split, "correction", [
            answer(f"Đếm sự kiện ngày {first}/1/2025.", "events", f"2025-01-{first:02d}"),
            answer(f"Tôi nhầm, đổi sang ngày {corrected}/1/2025.", "events",
                   f"2025-01-{corrected:02d}", reference=1),
        ])
        add(f"{split}_correction_filter", split, "correction", [
            answer(f"Doanh thu toàn thời gian từ kênh {initial_channel}.", "revenue",
                   filters=[{"campaign_channel": initial_channel}]),
            answer(f"Sửa kênh thành {replacement_channel}.", "revenue",
                   filters=[{"campaign_channel": replacement_channel}], reference=1),
        ])
        add(f"{split}_noise_social", split, "noise", [
            answer(f"Số phiên ngày {noise_day}/1/2025?", "sessions", f"2025-01-{noise_day:02d}"),
            {"question": "Cảm ơn, câu trả lời hữu ích." if split == "dev" else "Rất rõ, cảm ơn bạn.",
             "action": "conversation"},
            answer("Còn phân theo thiết bị thì sao?" if split == "dev" else "Và theo kênh tiếp thị?",
                   "sessions", f"2025-01-{noise_day:02d}",
                   breakdown="device_type" if split == "dev" else "campaign_channel", reference=1),
        ])
        add(f"{split}_noise_new_topic", split, "noise", [
            answer(f"{return_metric.capitalize()} ngày {new_first}/1/2025?", return_metric,
                   f"2025-01-{new_first:02d}"),
            {"question": "Chào bạn, tôi đang xem báo cáo." if split == "dev" else "Xin chào, tôi đang đọc báo cáo.",
             "action": "conversation"},
            answer(f"Đếm sự kiện ngày {new_second}/1/2025.", "events", f"2025-01-{new_second:02d}"),
        ])
        add(f"{split}_topic_return", split, "topic_switch_return", [
            answer(f"{return_metric.capitalize()} ngày {switch_first}/1/2025?", return_metric,
                   f"2025-01-{switch_first:02d}"),
            answer(f"Có bao nhiêu {ambiguous_final} ngày {switch_second}/1/2025?", ambiguous_final,
                   f"2025-01-{switch_second:02d}"),
            answer(f"Quay lại {return_metric} câu đầu, phân theo danh mục.", return_metric,
                   f"2025-01-{switch_first:02d}", breakdown="item_category", reference=1),
        ])
        add(f"{split}_topic_independent", split, "topic_switch_return", [
            answer(f"Số người mua từ thiết bị {independent_device} ngày {independent_day}/1/2025?",
                   "buyers", f"2025-01-{independent_day:02d}", [{"device_type": independent_device}]),
            answer(f"Câu hỏi mới, không dùng bộ lọc cũ: {ambiguous_final} toàn bộ thời gian.",
                   ambiguous_final, "all"),
        ])

    def long_dialogue(split, n):
        base = date(2025, 1, 5) if split == "dev" else date(2025, 1, 20)
        target_metric = "revenue" if split == "dev" else "buyers"
        first_day = base.isoformat()
        first_label = f"{base.day}/{base.month}/2025"
        turns = [answer(f"{target_metric.capitalize()} ngày {first_label} là bao nhiêu?", target_metric, first_day)]
        for i in range(2, n):
            if i % 3 == 0:
                turns.append({"question": "Cảm ơn." if split == "dev" else "Rõ rồi, cảm ơn.",
                              "action": "conversation"})
            else:
                # Explicit standalone requests verify that unrelated turns do
                # not overwrite the first result selected at the end.
                day = base + timedelta(days=i)
                metric = ("users" if i % 2 else "events") if split == "dev" else ("events" if i % 2 else "sessions")
                turns.append(answer(f"Số {metric} ngày {day.day}/{day.month}/2025?", metric, day.isoformat()))
        turns.append(answer(f"Quay lại {target_metric} câu đầu.", target_metric, first_day, reference=1))
        return turns

    add("dev_long_8", "dev", "long_reference", long_dialogue("dev", 8))
    add("test_long_10", "test", "long_reference", long_dialogue("test", 10))
    add("dev_long_12", "dev", "long_reference", long_dialogue("dev", 12))
    add("test_long_12", "test", "long_reference", long_dialogue("test", 12))

    for split in ("dev", "test"):
        if split == "dev":
            ambiguous_first, ambiguous_second, ambiguous_metric, ambiguous_final = 3, 4, "revenue", "buyers"
            independent_day, independent_device, independent_metric = 6, "mobile", "revenue"
        else:
            ambiguous_first, ambiguous_second, ambiguous_metric, ambiguous_final = 23, 24, "users", "events"
            independent_day, independent_device, independent_metric = 29, "tablet", "sessions"
        add(f"{split}_ambiguous_reference", split, "ambiguity_and_independence", [
            answer(f"{ambiguous_metric} ngày {ambiguous_first}/1/2025?", ambiguous_metric,
                   f"2025-01-{ambiguous_first:02d}"),
            answer(f"Số {ambiguous_final} ngày {ambiguous_second}/1/2025?", ambiguous_final,
                   f"2025-01-{ambiguous_second:02d}"),
            {"question": f"Chia kết quả {ambiguous_metric} đó theo danh mục.", "action": "clarify",
             "ask_fields": ["context:reference"]},
            {**answer(f"Kết quả {ambiguous_metric}.", ambiguous_metric,
                      f"2025-01-{ambiguous_first:02d}", breakdown="item_category",
                      reference=1), "action": "clarification_answer",
             "oracle_answers": {"context:reference": ["oracle:turn:1"]}, "oracle_reference_turn": 1},
            answer(f"Đổi sang tổng {ambiguous_final} toàn bộ thời gian.", ambiguous_final, "all"),
        ])
        add(f"{split}_no_inherit", split, "ambiguity_and_independence", [
            answer(f"Doanh thu từ thiết bị {independent_device} ngày {independent_day}/1/2025?",
                   "revenue", f"2025-01-{independent_day:02d}", [{"device_type": independent_device}]),
            answer(f"Câu hỏi mới: tổng {independent_metric} toàn bộ dữ liệu, không lọc thiết bị.", independent_metric, "all"),
        ])
    return scenarios


def build_interactions():
    interactions = []

    def add_period(i, split, target):
        cid = f"clarify_period_{i:02d}"
        prompts = [
            ("Cho biết doanh thu.", "Tôi muốn xem doanh thu.", "Tính doanh thu giúp tôi.", "Báo cáo doanh số."),
            ("Tính số người mua.", "Báo cáo lượng người mua.", "Có bao nhiêu người đã mua?", "Tôi muốn xem số khách mua hàng."),
            ("Báo cáo số người dùng.", "Tổng người dùng là bao nhiêu?", "Tính số người dùng hoạt động.", "Cho tôi lượng người dùng khác nhau."),
            ("Có bao nhiêu sự kiện?", "Tổng lượt sự kiện là bao nhiêu?", "Báo cáo số sự kiện đã ghi nhận.", "Tính lượt hoạt động."),
        ]
        metric_index = (i - 1) % 4
        metric = ["revenue", "buyers", "users", "events"][metric_index]
        variant_index = (i - 1) // 4
        prompt = prompts[metric_index][variant_index]
        state_range = target
        interactions.append({"id": cid, "split": split, "family": f"{split}_missing_period",
            "cluster_id": cid, "phenomenon": "missing_period", "question": prompt,
            "ask_fields": ["time_range"], "oracle_answers": {"time_range": [target]},
            "state": {"metric": metric, "time_range": state_range, "filters": [], "breakdown": None},
            "gold_sql": v2.sql(where_for(metric, target)), "expected_result": v2.evaluate(ROWS, where_for(metric, target)),
            "tags": ["clarification", "missing_period"]})
        explicit = ("toàn bộ dữ liệu" if target == "all" else "7 ngày gần nhất")
        control_id = f"control_period_{i:02d}"
        interactions.append({"id": control_id, "split": split, "family": f"{split}_missing_period",
            "cluster_id": cid, "phenomenon": "explicit_period_control", "control_of": cid,
            "question": f"{prompt[:-1]} trong {explicit}.", "ask_fields": [], "oracle_answers": {},
            "state": {"metric": metric, "time_range": state_range, "filters": [], "breakdown": None},
            "gold_sql": v2.sql(where_for(metric, target)), "expected_result": v2.evaluate(ROWS, where_for(metric, target)),
            "tags": ["clarification_control", "period_present"]})

    # Both interpretations occur equally often. They differ observably in this
    # 50-day fixture, so choosing at random cannot look accurate by coincidence.
    for i in range(1, 17):
        split = "dev" if i <= 8 else "test"
        target = "all" if i % 2 else "last_7"
        add_period(i, split, target)

    metric_questions = [
        ("Số khách hàng trong toàn bộ dữ liệu là bao nhiêu?", "buyers"),
        ("Cho tôi số khách hàng có hoạt động, tính toàn thời gian.", "users"),
        ("Thống kê khách hàng toàn thời gian giúp tôi.", "buyers"),
        ("Báo cáo số khách hàng trong toàn bộ dữ liệu.", "users"),
    ]
    for i, (question, target) in enumerate(metric_questions, 1):
        split = "dev" if i <= 2 else "test"
        cid = f"clarify_metric_{i:02d}"
        interactions.append({"id": cid, "split": split, "family": f"{split}_ambiguous_metric",
            "cluster_id": cid, "phenomenon": "ambiguous_metric", "question": question,
            "ask_fields": ["recipe"], "oracle_answers": {"recipe": [target]},
            "state": {"metric": target, "time_range": "all", "filters": [], "breakdown": None},
            "gold_sql": v2.sql(where_for(target, "all")), "expected_result": v2.evaluate(ROWS, where_for(target, "all")),
            "tags": ["clarification", "ambiguous_metric"]})
        control_id = f"control_metric_{i:02d}"
        explicit = "người mua" if target == "buyers" else "người dùng duy nhất"
        control_question = question.replace("khách hàng", explicit)
        interactions.append({"id": control_id, "split": split, "family": f"{split}_ambiguous_metric",
            "cluster_id": cid, "phenomenon": "explicit_metric_control", "control_of": cid,
            "question": control_question, "ask_fields": [], "oracle_answers": {},
            "state": {"metric": target, "time_range": "all", "filters": [], "breakdown": None},
            "gold_sql": v2.sql(where_for(target, "all")), "expected_result": v2.evaluate(ROWS, where_for(target, "all")),
            "tags": ["clarification_control", "metric_present"]})
    return interactions


def build():
    ROWS
    fixture = v2.fixture(ROWS).replace("Synthetic product events v2", "Synthetic product events ablation v1")
    fixture = fixture.replace("Frozen generated 96-row benchmark fixture",
                              "Frozen 96-row 50-day event fixture for ablation study")
    (ROOT / "fixture.sql").write_text(fixture, encoding="utf-8")
    projection = [{key: row[key] for key in ("event_id", "event_date", "event_name", "user_id",
                  "session_id", "item_category", "revenue", "ep")}
                  for row in sorted(ROWS, key=lambda item: item["event_id"])]
    canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    (ROOT / "fixture_rows.json").write_text(canonical, encoding="utf-8")
    (ROOT / "dialogues.yaml").write_text(yaml.safe_dump(build_memory(), sort_keys=False,
        allow_unicode=True, width=110), encoding="utf-8")
    (ROOT / "interactions.yaml").write_text(yaml.safe_dump(build_interactions(), sort_keys=False,
        allow_unicode=True, width=110), encoding="utf-8")
    # The single-turn accuracy regression suite remains exactly the frozen v2
    # suite, whose fixture is loaded separately. Keeping an empty file makes
    # that relationship explicit without re-annotating duplicate questions.
    (ROOT / "cases.yaml").write_text("[]\n", encoding="utf-8")
    return ROWS


if __name__ == "__main__":
    print(f"generated rows={len(build())}; memory_scenarios={len(build_memory())}; "
          f"interaction_items={len(build_interactions())}; source_digest="
          f"{hashlib.sha256((ROOT / 'fixture_rows.json').read_bytes()).hexdigest()}")
