"""The dashboard narrative (RFP area 4): "What this view shows".

1. The semantic layer computes a fact bundle for the view's own query --
   totals, the latest movement, leading and lagging districts, the largest
   changes -- in SQL.
2. The model is handed those facts and writes one paragraph, told to quote
   them exactly, calculate nothing and state every caveat.
3. Every number in the paragraph must be one of the facts. If one is not, the
   model is asked once more; then the paragraph is rendered from a template
   over the same facts. No unvalidated number is ever returned.

With no model configured and nothing cached, step 2 is skipped and the
template is used, so the panel always describes the real figures and says
which of the two wrote it.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import duckdb

from app.exports import provenance
from app.llm import numbers
from app.llm.calls import logged_call
from app.llm.provider import Message, Provider
from app.semantic import service as semantic
from app.semantic.registry import DIMENSIONS_BY_ID
from app.semantic.spec import QuerySpec

SYSTEM = """\
You write a short paragraph, three to five sentences, describing a dashboard \
view of Odisha agricultural statistics. You are given the figures for the \
view; they are everything you know.

Rules:
- Use only numbers from the facts, the filters, the period or the caveats. \
Quote them as given; you may round to fewer decimal places. Do not add, \
subtract, average, count, convert units or compute percentages or differences.
- Name the unit of each figure.
- Add no causes, context or explanation that the facts do not state.
- State every caveat you are given, in plain language.
- Plain prose: no lists, no headings, no markdown.
"""

# How many leaders, laggards and changes are shown to the model and the reader.
SHOWN = 3


def _period_text(spec: QuerySpec) -> Optional[str]:
    if spec.period and spec.period.from_year and spec.period.to_year:
        if spec.period.from_year == spec.period.to_year:
            return spec.period.from_year
        return f"{spec.period.from_year} to {spec.period.to_year}"
    for item in spec.filters:
        if item.dimension == "agri_year" and item.op in ("eq", "in"):
            return ", ".join(item.values)
    return None


def facts_used(bundle: dict[str, Any], unit: str, label: str) -> list[dict[str, Any]]:
    """The bundle, flattened into the labelled figures the paragraph may quote."""
    facts: list[dict[str, Any]] = []
    headline = bundle["headline"]
    if headline.get("value") is not None:
        facts.append({"label": label, "value": headline["value"], "unit": unit,
                      "scope": "whole selection"})
        facts.append({"label": "Districts with data", "value": headline["districts_covered"],
                      "unit": "districts", "scope": None})
    movement = bundle.get("movement")
    if movement:
        facts.append({"label": label, "value": movement["from_value"], "unit": unit,
                      "scope": movement["from_period"]})
        facts.append({"label": label, "value": movement["to_value"], "unit": unit,
                      "scope": movement["to_period"]})
        if movement.get("percent_change") is not None:
            facts.append({
                "label": "Change year on year", "value": movement["percent_change"], "unit": "%",
                "scope": f"{movement['from_period']} to {movement['to_period']}",
            })
    for row in bundle["leaders"][:SHOWN]:
        facts.append({"label": f"Highest: {row['district']}", "value": row["value"],
                      "unit": unit, "scope": f"rank {row['rank']}"})
    for row in bundle["laggards"][:SHOWN]:
        facts.append({"label": f"Lowest: {row['district']}", "value": row["value"],
                      "unit": unit, "scope": f"rank {row['rank']}"})
    for row in bundle["largest_changes"][:SHOWN]:
        facts.append({
            "label": f"Largest change: {row['district']}", "value": row["percent_change"],
            "unit": "%", "scope": f"{row['from_period']} to {row['to_period']}",
        })
    return facts


def _figure(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def template_narrative(
    label: str, unit: str, scope: str, period: Optional[str], bundle: dict[str, Any]
) -> str:
    """The same facts, stated plainly. Used when model prose cannot be trusted."""
    headline = bundle["headline"]
    if headline.get("value") is None:
        return f"No figures are recorded for {scope or 'this selection'}."
    when = f", {period}" if period else ""
    where = f" ({scope})" if scope else ""
    sentences = [
        f"{label}{when}{where}: {_figure(headline['value'])} {unit}, across "
        f"{headline['districts_covered']} districts with data."
    ]
    leaders, laggards = bundle["leaders"][:SHOWN], bundle["laggards"][:SHOWN]
    if leaders:
        sentences.append(
            "Highest: "
            + ", ".join(f"{r['district']} ({_figure(r['value'])} {unit})" for r in leaders)
            + "."
        )
    # Only when the two lists cannot name the same district.
    if laggards and headline["districts_covered"] > 2 * SHOWN:
        sentences.append(
            "Lowest: "
            + ", ".join(f"{r['district']} ({_figure(r['value'])} {unit})" for r in laggards)
            + "."
        )
    movement = bundle.get("movement")
    if movement:
        sentences.append(
            f"It was {_figure(movement['from_value'])} {unit} in {movement['from_period']} and "
            f"{_figure(movement['to_value'])} {unit} in {movement['to_period']}."
        )
    return " ".join(sentences)


def narrate(con: duckdb.DuckDBPyConnection, spec: QuerySpec, provider: Provider) -> dict[str, Any]:
    bundle = semantic.run_narrative_facts(con, spec)
    context = bundle["applied_context"]
    label, unit = context["metric_label"], context["unit"]
    filters = semantic.describe_filters(con, context["filters"])
    scope = "; ".join(
        f"{item['dimension_label']}: {', '.join(item['values_display'])}"
        for item in filters
        if item["dimension"] in DIMENSIONS_BY_ID
    )
    period = _period_text(spec)
    facts = facts_used(bundle, unit, label)
    caveats = bundle["caveats"]
    calls: list[dict[str, Any]] = []

    payload = {
        "metric": label,
        "unit": unit,
        "filters": [
            f"{item['dimension_label']}: {', '.join(item['values_display'])}" for item in filters
        ],
        "period": period,
        "facts": facts,
        "caveats": [caveat["message"] for caveat in caveats],
    }
    allowed = numbers.collect(
        [payload["facts"], payload["filters"], payload["period"], payload["caveats"]]
    )

    text, source, model = None, "template", None
    if facts:
        messages = [Message("user", json.dumps(payload, ensure_ascii=False, indent=1))]
        for purpose in ("narrative", "narrative_retry"):
            completion = logged_call(con, provider, purpose, SYSTEM, messages, "text", calls)
            if completion is None:
                break
            candidate = completion.text.strip()
            bad = numbers.unsupported(candidate, allowed)
            if not bad:
                text, source, model = candidate, "model", completion.model
                break
            messages = [
                *messages,
                Message("model", completion.text),
                Message(
                    "user",
                    f"These numbers are not in the facts you were given: {', '.join(bad)}. "
                    "Rewrite the paragraph using only numbers from the facts, filters, "
                    "period and caveats.",
                ),
            ]
    if text is None:
        text = template_narrative(label, unit, scope, period, bundle)
        # Built from the facts, so this cannot fail; checked anyway, because an
        # unvalidated number must never be shown.
        if numbers.unsupported(text, numbers.collect([facts, payload["filters"], period])):
            raise RuntimeError("template narrative quoted a number not in its facts")

    return {
        "narrative": text,
        "narrative_source": source,
        "model": model,
        "facts_used": facts,
        "caveats": caveats,
        "applied_context": {
            **context,
            "filters": filters,
            "provenance_notes": provenance.notes_from_context(context),
        },
        "data_origin": context["data_origin"],
        "served_from_cache": any(call["served_from_cache"] for call in calls),
        "llm_calls": calls,
    }
