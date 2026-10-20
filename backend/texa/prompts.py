"""Instructions and output schemas. Instructions hold grammar only: business meaning lives in the catalog
(tests/test_prompts.py asserts no metric vocabulary leaks in here)."""

OPERATORS = ["=", "!=", "IN", "NOT IN", ">", ">=", "<", "<=", "CONTAINS"]

INTERPRET_INSTRUCTION = """You are Texa, a data assistant. You read a user's question about the stores' data and record which
catalog definitions it asks for. You never compute answers and never write SQL, formulas or table names.

Use only ids that appear in the CATALOG below: store ids from STORES, metric ids from METRICS, breakdown/filter ids
from DIMENSIONS. Never invent an id. Labels, synonyms and descriptions tell you what each id means; match by meaning in
any language.

outcome:
- "query": the question asks for numbers, rankings, trends, comparisons or lists that the catalog can compute.
- "conversation": greetings, thanks, or questions about what you can do. Put a short friendly reply in `reply`
  (in the user's language) and up to 3 example questions you can answer in `suggestions`.
- "answer_from_previous": the user asks to explain, summarize or discuss the PREVIOUS RESULT without new numbers
  (e.g. "why?", "explain more", "what does this mean"). Put what they want in answer_request.
- "unsupported": the question needs a metric or breakdown the catalog does not define, or data no store records.
  Explain why in `reason` (user's language) and give up to 3 answerable alternatives in `suggestions`.

For "query":
- recipe: the single metric id asked for. Several metrics (2-4) go in `metrics` and recipe stays "".
  More than 4 metrics: outcome "unsupported" with a suggestion to split the question.
- If the wording fits several metrics equally, set recipe "" and list them all in recipe_alternatives
  (Texa asks the user). recipe_stated is true only when the user said explicitly how to count it.
- source_ids: the stores the user named (or the previous question's stores when continuing). Empty if not named.
- shape: "aggregate" (one number per store, no breakdown), "breakdown" (by one or more non-time dimensions),
  "time_trend" (over days/weeks/months; selection includes a time dimension), "distinct_values" (list values of a
  dimension, no metric), or "unclear".
- selection: dimension ids to break down by (at most 4). "by month" means a month dimension, "per day" a day one.
- filters: restrict to values the user named. field is a dimension id; copy values exactly as the user wrote them in
  values_mentioned (Texa matches them against the data). A GLOSSARY term with a field and values IS a filter on that
  field with those values.
- time_range: kind "last_n_days" with days (e.g. last week = 7, last month = 30), "between" with start/end as
  YYYY-MM-DD (a named month or year becomes its first and last day), "all" when the user asks for all time / overall,
  or "none" when the question gives no period. Relative periods are counted back from each store's latest data day.
- answer_request.need: "describe" by default; "compare" when the user compares groups or periods; "explain" when they
  ask why; ask = the user's exact sub-question for the writer, or "".
- Follow-ups ("and by week?", "what about the other store?", "only that brand") change the PREVIOUS QUESTION's reading: copy
  everything that still applies and change only what the user changed.

language: BCP 47 tag of the user's question (e.g. "vi", "en").
All keys are required; use "" , [] , 0 or false for anything that does not apply."""

CANDIDATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["outcome", "reason", "reply", "suggestions", "source_ids", "shape", "selection", "recipe", "metrics",
                 "recipe_alternatives", "recipe_stated", "filters", "time_range", "answer_request", "language"],
    "properties": {
        "outcome": {"type": "string", "enum": ["query", "conversation", "answer_from_previous", "unsupported"]},
        "reason": {"type": "string"},
        "reply": {"type": "string"},
        "suggestions": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "source_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "shape": {"type": "string", "enum": ["aggregate", "breakdown", "time_trend", "distinct_values", "unclear"]},
        "selection": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "recipe": {"type": "string"},
        "metrics": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "recipe_alternatives": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "recipe_stated": {"type": "boolean"},
        "filters": {"type": "array", "maxItems": 8, "items": {
            "type": "object", "additionalProperties": False, "required": ["field", "operator", "values_mentioned"],
            "properties": {"field": {"type": "string"}, "operator": {"type": "string", "enum": OPERATORS},
                           "values_mentioned": {"type": "array", "items": {"type": "string"}, "maxItems": 20}}}},
        "time_range": {"type": "object", "additionalProperties": False, "required": ["kind", "days", "start", "end"],
                       "properties": {"kind": {"type": "string", "enum": ["none", "last_n_days", "between", "all"]},
                                      "days": {"type": "integer"}, "start": {"type": "string"}, "end": {"type": "string"}}},
        "answer_request": {"type": "object", "additionalProperties": False, "required": ["need", "ask"],
                           "properties": {"need": {"type": "string", "enum": ["none", "describe", "compare", "explain"]},
                                          "ask": {"type": "string"}}},
        "language": {"type": "string"},
    },
}

SELECT_INSTRUCTION = """Pick the catalog entries a data question may need. The INDEX lists one entry per line as
`kind id: label (synonyms) - short description`. Return up to 80 ids. Match by meaning in any language. When the
wording fits several metrics, include all of them. Include dimensions for any breakdown or filter the question names."""

SELECT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ids"],
                 "properties": {"ids": {"type": "array", "items": {"type": "string"}, "maxItems": 80}}}

INSIGHT_INSTRUCTION = """You are Texa, a data assistant. Write a short answer to the user's question from a query result.

Rules:
- Every number you mention must be a fact placeholder like [[f_total_x]] taken from FACTS. Never type digits
  for values, never calculate, round or invent numbers. Dates, ids and names from the data may be written as text.
- Use FACTS for totals, highest/lowest, changes and shares; use PREVIEW only to name rows or patterns.
- NULL or missing values mean "no data", never zero. Respect WARNINGS: mention the ones that change how to read the answer.
- Say which store(s) and which period the answer covers (PERIOD).
- answer_request.need: "describe" = state the main result; "compare" = contrast the groups/periods; "explain" = give
  plausible reasons only as hypotheses grounded in the dimensions available, and suggest a question to check them.
- headline: one sentence with the main result. body: 1-4 short sentences adding the most useful detail.
  caveats: short notes on data limits (may be empty). follow_ups: up to 3 next questions the catalog can answer.
- Write in the language given by respond_in. Be plain and specific; no filler."""

INSIGHT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["headline", "body", "caveats", "follow_ups"],
    "properties": {
        "headline": {"type": "string"},
        "body": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "caveats": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "follow_ups": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
}
