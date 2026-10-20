"""The answer writer: reads facts + a bounded preview, cites numbers only through [[fact_id]] placeholders,
which the server replaces with formatted values. A sentence citing an unknown fact is dropped."""
import json
import re

from . import llm
from .facts import format_value
from .prompts import INSIGHT_INSTRUCTION, INSIGHT_SCHEMA

PLACEHOLDER = re.compile(r"\[\[\s*(f_[A-Za-z0-9_]+)\s*\]\]")


def substitute(text: str, facts: dict[str, dict], lang: str) -> str | None:
    """Replace placeholders; None when the text cites a fact that does not exist."""
    missing = False

    def repl(m):
        nonlocal missing
        f = facts.get(m.group(1))
        if f is None:
            missing = True
            return ""
        return format_value(f["value"], f["unit"], f.get("currency"), lang)

    out = PLACEHOLDER.sub(repl, text)
    return None if missing else out


def render(raw: dict, facts: list[dict], lang: str) -> tuple[dict, int]:
    by_id = {f["id"]: f for f in facts}
    dropped = 0
    body = []
    for sentence in raw["body"]:
        s = substitute(sentence, by_id, lang)
        if s is None:
            dropped += 1
        elif s.strip():
            body.append(s)
    headline = substitute(raw["headline"], by_id, lang)
    if headline is None:
        dropped += 1
        headline = body.pop(0) if body else ""
    caveats = [c for c in (substitute(c, by_id, lang) for c in raw["caveats"]) if c]
    follow_ups = [f for f in raw["follow_ups"] if not PLACEHOLDER.search(f)]
    return {"headline": headline, "body": body, "caveats": caveats, "follow_ups": follow_ups}, dropped


def template_answer(result: dict, lang: str) -> dict:
    """Used when the writer fails twice: a plain sentence built from the first facts."""
    facts = [f for f in result["facts"] if f["id"] != "f_rows" and f["unit"] != "text"][:3]
    parts = [f"{f['label']}: {format_value(f['value'], f['unit'], f.get('currency'), lang)}" for f in facts]
    return {"headline": "; ".join(parts) or ("No rows." if not lang.startswith("vi") else "Không có dữ liệu."),
            "body": [], "caveats": [], "follow_ups": []}


def build_payload(question: str, result: dict, cat, sources, lang: str, answer_request: dict) -> str:
    spec = result["query_spec"]
    payload = {
        "question": question,
        "respond_in": lang,
        "answer_request": answer_request,
        "reading": {
            "metrics": [cat.mets[m].label for m in ([spec["recipe"]] if spec["recipe"] else spec["metrics"])],
            "breakdowns": [cat.dims[d].label for d in spec["selection"]],
            "filters": [{"field": cat.dims[f["field"]].label, "operator": f["operator"], "values": f["values"]}
                        for f in spec["filters"]],
        },
        "period": {sources[s].label: p for s, p in result["period"].items() if s in result["sources"]},
        "columns": [{k: c[k] for k in ("name", "label", "unit")} | ({"currency": "per store"} if c["unit"] == "currency" else {})
                    for c in result["columns"]],
        "store_currency": {sources[s].label: c for s, c in result["currency_of"].items()},
        "facts": [{"id": f["id"], "label": f["label"],
                   "value": format_value(f["value"], f["unit"], f.get("currency"), "en")} for f in result["facts"]],
        "preview": result["model_preview"],
        "preview_note": "top rows plus an 'Others' row" if result.get("model_preview_grouped") else "",
        "row_count": result["row_count"],
        "partial": result["partial"],
        "warnings": result["warnings"],
        "unavailable_metrics": result["unavailable_metrics"],
    }
    text = json.dumps(payload, ensure_ascii=False, default=str)
    while len(text) > 120_000 and len(payload["preview"]) > 10:  # halve rows until the prompt fits
        payload["preview"] = payload["preview"][: len(payload["preview"]) // 2]
        text = json.dumps(payload, ensure_ascii=False, default=str)
    return text


def write(question: str, result: dict, cat, sources, *, lang: str, answer_request: dict, model: str | None,
          turn_id=None, step=None) -> dict:
    prompt = build_payload(question, result, cat, sources, lang, answer_request)
    with step("write_answer") as s:
        for attempt in range(2):
            try:
                raw = llm.generate_structured(model=model, system=INSIGHT_INSTRUCTION, prompt=prompt,
                                              schema=INSIGHT_SCHEMA, name="insight", turn_id=turn_id)
            except llm.LLMError as e:
                if attempt == 1 or e.code not in ("MODEL_OUTPUT_INVALID", "MODEL_OUTPUT_TRUNCATED"):
                    if e.code in ("MODEL_OUTPUT_INVALID", "MODEL_OUTPUT_TRUNCATED"):
                        s.note("writer failed; plain summary")
                        return template_answer(result, lang)
                    raise
                continue
            answer, dropped = render(raw, result["facts"], lang)
            if answer["headline"]:
                if dropped:
                    s.note(f"dropped {dropped} sentence(s) citing unknown facts")
                return answer
        s.note("writer failed; plain summary")
        return template_answer(result, lang)
