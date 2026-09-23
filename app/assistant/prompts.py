"""What the model is shown. Nothing else reaches it.

Two prompts. The first turns a question into a query spec, given the semantic
registry: metric and dimension ids, their rules, the values each dimension may
take and the years each metric covers. The second turns result rows into one
paragraph. Neither contains a table name, a column name or SQL -- the model
works in the registry's vocabulary and the backend does the rest.
"""
from __future__ import annotations

import json
from typing import Any

import duckdb

from app.semantic import service as semantic

INTERPRET_SYSTEM = """\
You translate a question about Odisha agricultural statistics into a query \
specification for a statistics service. You never answer the question and you \
never state figures of your own.

You are given the service's catalogue: its metrics, its dimensions, the values \
each dimension may take and the years each metric covers. That catalogue is \
everything the service holds.

Reply with one JSON object and nothing else, in one of two forms.

To query:
{"action": "query", "spec": {"metric": "<metric id>", "dimensions": ["<dimension id>"], \
"filters": [{"dimension": "<dimension id>", "op": "eq" | "in" | "not_in" | "between" | \
"gte" | "lte", "values": ["<value>"]}], "period": {"from": "YYYY-YY", "to": "YYYY-YY"} or \
null, "order_by": {"field": "value" or a dimension in the query, "direction": "asc" | \
"desc"} or null, "limit": <1 to 100>}}

To refuse:
{"action": "refuse", "limitation": "<one or two sentences naming what the question \
needs that the catalogue does not hold>"}

Rules:
- Use only metric ids, dimension ids and values from the catalogue. Filter \
district, block and crop by their value (for example OD07), not their label.
- Respect each metric's allowed_dimensions, required_dimensions, \
forbidden_dimensions and requires_scope. A dimension in requires_scope must be \
filtered to specific values or grouped by.
- Group by one dimension unless the question needs two.
- Pin the years: filter agri_year, set period, or group by agri_year for a \
trend. Choose years inside the metric's coverage.
- Refuse any question that needs something the catalogue does not hold: other \
states or countries, policy, causes, opinions, general knowledge, or a grain or \
year a metric does not cover. An accurate refusal is a correct answer; a guess \
is not.
- If the service rejects your spec you will be told why. Correct it, or refuse.
"""

ANSWER_SYSTEM = """\
You write a one-paragraph answer to a question about Odisha agricultural \
statistics, using only the result you are given.

Rules:
- Use only numbers that appear in the rows, the filters, the period or the \
caveats. Quote them as given; you may round to fewer decimal places. Do not \
add, subtract, average, count, convert units or compute percentages or \
differences. Do not repeat a number from the question unless it appears in \
the result.
- Name the unit of the values.
- Add no context, causes or explanations that are not in the result.
- State every caveat you are given, in plain language.
- If the rows answer only part of the question, say what they do show.
- One paragraph of plain prose: no lists, no headings, no markdown.
"""

_REGISTRY_CACHE: dict[str, str] = {}


def registry_payload(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """The catalogue, in registry vocabulary only."""
    spans = semantic.coverage(con)
    metrics = [
        {
            "id": metric["metric_id"],
            "label": metric["label"],
            "unit": metric["unit"],
            "definition": metric["definition"],
            "allowed_dimensions": metric["allowed_dimensions"],
            "required_dimensions": metric["required_dimensions"],
            "forbidden_dimensions": metric["forbidden_dimensions"],
            "requires_scope": metric["requires_scope"],
            "coverage": spans[str(metric["metric_id"])],
        }
        for metric in semantic.metric_catalogue()
    ]
    dimensions = []
    for dimension in semantic.dimension_catalogue():
        # Published sandbox estimates are not offered (predicted_yield is not
        # in the catalogue), and leaving their values out keeps the catalogue,
        # and so every cache key, unchanged when a run is published.
        values = semantic.dimension_values(
            con, str(dimension["dimension_id"]), include_predictions=False
        )
        dimensions.append(
            {
                "id": dimension["dimension_id"],
                "label": dimension["label"],
                "description": dimension["description"],
                "values": (
                    [{"value": v["value"], "label": v["label"]} for v in values]
                    if dimension["is_coded"]
                    else [v["value"] for v in values]
                ),
            }
        )
    return {"metrics": metrics, "dimensions": dimensions}


def registry_text(con: duckdb.DuckDBPyConnection) -> str:
    fingerprint = semantic._database_fingerprint(con)
    if fingerprint not in _REGISTRY_CACHE:
        _REGISTRY_CACHE[fingerprint] = json.dumps(
            registry_payload(con), ensure_ascii=False, separators=(",", ":")
        )
    return _REGISTRY_CACHE[fingerprint]


def interpret_message(con: duckdb.DuckDBPyConnection, question: str) -> str:
    return f"Catalogue:\n{registry_text(con)}\n\nQuestion: {question}"


def correction_message(problem: dict[str, Any]) -> str:
    return (
        "The service rejected that spec:\n"
        f"{json.dumps(problem, ensure_ascii=False)}\n"
        "Reply with a corrected spec in the same JSON form, or refuse."
    )


def answer_message(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=1)


def number_correction_message(unsupported: list[str]) -> str:
    return (
        f"These numbers are not in the result you were given: {', '.join(unsupported)}. "
        "Rewrite the paragraph using only numbers from the rows, filters, period and caveats."
    )
