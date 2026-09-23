"""The conversational assistant (RFP area 5): question in, validated answer out.

The model never writes SQL and never computes a figure:

1. It is shown the registry and the question, and replies with a query spec
   or a refusal -- JSON only.
2. The spec is parsed into :class:`QuerySpec` (unknown keys rejected) and
   validated against the registry. A rejection goes back to the model once;
   a second rejection ends in a refusal that names what failed.
3. The semantic layer executes the validated spec. The model is never shown
   SQL, a table name or the database.
4. The rows go back to the model for one paragraph. Every number in it must
   be in the result; if not, it is asked once more, and then the paragraph is
   rendered from a template instead. No unvalidated number is ever returned.

The only route from model output to the database is (2): a spec that passed
validation, compiled into parameterised SQL by the semantic layer.
"""
from __future__ import annotations

import json
from typing import Any, Literal, Optional, Union

import duckdb
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.assistant import prompts
from app.assistant.starters import STARTERS
from app.llm import numbers
from app.llm.calls import logged_call as _call
from app.llm.provider import Message, Provider
from app.semantic import service as semantic
from app.semantic.registry import DIMENSIONS_BY_ID
from app.semantic.spec import QuerySpec, SpecError, validate_spec

# The assistant draws one chart and one table, so a spec asking for more rows
# than a reader can take in is cut to this.
MAX_ROWS = 100
# Rows shown to the model when it writes the answer.
ANSWER_ROWS = 50
RECORDS_PREVIEW = 25
TIME_DIMENSIONS = ("agri_year", "month")

GENERIC_REFUSAL = "This question needs data the loaded datasets do not hold."


class _QueryReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["query"]
    spec: QuerySpec


class _RefuseReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["refuse"]
    limitation: str = Field(min_length=1)


class _Reply(BaseModel):
    reply: Union[_QueryReply, _RefuseReply] = Field(discriminator="action")


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip()


def _parse(
    con: duckdb.DuckDBPyConnection, text: str
) -> tuple[Optional[Union[_QueryReply, _RefuseReply]], Optional[dict[str, Any]]]:
    """The model's reply as a validated spec or a refusal, or the problem with it."""
    try:
        raw = json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        return None, {"detail": "the reply was not JSON", "code": "malformed_reply"}
    try:
        reply = _Reply.model_validate({"reply": raw}).reply
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in error['loc'][1:])}: {error['msg']}"
            for error in exc.errors()
        )
        return None, {"detail": problems, "code": "malformed_reply"}
    if isinstance(reply, _QueryReply):
        try:
            validate_spec(reply.spec, semantic.known_values(con))
        except SpecError as exc:
            return None, exc.as_body()
        reply.spec = reply.spec.model_copy(
            update={"include_records": False, "limit": min(reply.spec.limit, MAX_ROWS)}
        )
    return reply, None


# --------------------------------------------------------------------------
# Describing a result
# --------------------------------------------------------------------------
def _period_text(spec: QuerySpec, rows: list[dict[str, Any]]) -> Optional[str]:
    if "agri_year" in spec.dimensions:
        years = sorted(str(row["agri_year"]) for row in rows if row.get("agri_year"))
        if years:
            return years[0] if years[0] == years[-1] else f"{years[0]} to {years[-1]}"
    for item in spec.filters:
        if item.dimension == "agri_year":
            if item.op == "between":
                return f"{item.values[0]} to {item.values[1]}"
            if item.op in ("eq", "in"):
                return ", ".join(sorted(item.values))
    if spec.period and (spec.period.from_year or spec.period.to_year):
        if spec.period.from_year and spec.period.to_year:
            return f"{spec.period.from_year} to {spec.period.to_year}"
        if spec.period.from_year:
            return f"From {spec.period.from_year}"
        return f"Up to {spec.period.to_year}"
    return None


def _scope_text(filters: list[dict[str, Any]]) -> str:
    return "; ".join(
        f"{item['dimension_label']}: {', '.join(item['values_display'])}" for item in filters
    )


def _interpretation(
    spec: QuerySpec,
    context: dict[str, Any],
    period: Optional[str],
    corrected: bool,
    model: str,
) -> dict[str, Any]:
    order = None
    if spec.order_by is not None:
        field, descending = spec.order_by.field, spec.order_by.direction == "desc"
        if field == "value":
            order = f"By value, {'highest' if descending else 'lowest'} first"
        else:
            label = DIMENSIONS_BY_ID[field].label.lower()
            order = f"By {label}, {'descending' if descending else 'ascending'}"
    return {
        "metric": spec.metric,
        "metric_label": context["metric_label"],
        "unit": context["unit"],
        "dimensions": [
            {"id": d, "label": DIMENSIONS_BY_ID[d].label} for d in spec.dimensions
        ],
        "filters": context["filters"],
        "period": period,
        "order": order,
        "limit": spec.limit,
        "corrected": corrected,
        "model": model,
    }


def _chart(spec: QuerySpec, rows: list[dict[str, Any]], context: dict[str, Any]) -> Optional[dict]:
    """A bar chart for one category, a line for one time dimension, else none."""
    if len(spec.dimensions) != 1 or len(rows) < 2:
        return None
    dimension = spec.dimensions[0]
    data = [{dimension: row[dimension], "value": row["value"]} for row in rows]
    kind = "line" if dimension in TIME_DIMENSIONS else "bar"
    if kind == "line":
        data.sort(key=lambda point: str(point[dimension]))
    return {
        "kind": kind,
        "x_key": dimension,
        "y_key": "value",
        "unit": context["unit"],
        "series_label": context["metric_label"],
        "data": data,
    }


def _model_rows(spec: QuerySpec, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows as the model sees them: labels and values, no codes."""
    return [
        {**{d: row[d] for d in spec.dimensions}, "value": row["value"]}
        for row in rows[:ANSWER_ROWS]
    ]


def _figure(value: object) -> str:
    return f"{float(value):,.2f}".rstrip("0").rstrip(".")  # type: ignore[arg-type]


def template_answer(spec: QuerySpec, rows: list[dict[str, Any]], context: dict[str, Any]) -> str:
    """A plain rendering of the rows, used when model prose cannot be trusted."""
    label, unit = context["metric_label"], context["unit"]
    scope = _scope_text(context["filters"])
    head = f"{label} ({unit})" + (f" for {scope}" if scope else "")
    if not spec.dimensions:
        return f"{head}: {_figure(rows[0]['value'])} {unit}."
    if len(spec.dimensions) == 1:
        dimension = spec.dimensions[0]
        valued = [row for row in rows if row["value"] is not None]
        if not valued:
            return f"{head}: no values recorded."
        if dimension in TIME_DIMENSIONS:
            ordered = sorted(valued, key=lambda row: str(row[dimension]))
            first, last = ordered[0], ordered[-1]
            return (
                f"{head}: {_figure(first['value'])} in {first[dimension]} and "
                f"{_figure(last['value'])} in {last[dimension]}."
            )
        listed = ", ".join(f"{row[dimension]} {_figure(row['value'])}" for row in valued[:5])
        return f"{head}, in the order requested: {listed}."
    listed = "; ".join(
        ", ".join(str(row[d]) for d in spec.dimensions) + f": {_figure(row['value'])}"
        for row in rows[:5]
    )
    return f"{head}, in the order requested: {listed}."


# --------------------------------------------------------------------------
# The pipeline
# --------------------------------------------------------------------------
def _base(question: str, calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "question": question,
        "answer_source": None,
        "limitation": None,
        "interpretation": None,
        "query_spec": None,
        "chart_spec": None,
        "applied_filters": [],
        "source_datasets": [],
        "period": None,
        "rows": [],
        "records_preview": [],
        "records_total": 0,
        "caveats": [],
        "applied_context": None,
        "data_origin": {},
        "grain_source": {},
        "provenance_notes": [],
        "llm_calls": calls,
        "served_from_cache": any(call["served_from_cache"] for call in calls),
    }


def _unavailable(question: str, calls: list[dict[str, Any]]) -> dict[str, Any]:
    reason = calls[-1]["error"] if calls else None
    return {
        **_base(question, calls),
        "status": "unavailable",
        "answer": (
            "The language model could not be reached and this question has not been "
            "answered before, so it could not be interpreted. The starter questions "
            "answer from the stored cache."
        ),
        "limitation": reason,
    }


def _declined(
    question: str, calls: list[dict[str, Any]], limitation: str, **extra: Any
) -> dict[str, Any]:
    return {
        **_base(question, calls),
        "status": "declined",
        "answer": "This cannot be answered from the loaded data.",
        "limitation": limitation,
        **extra,
    }


def _rejection_text(problem: dict[str, Any]) -> str:
    return (
        "The question could not be turned into a query the loaded data supports. "
        f"The last reading was rejected: {problem['detail']}."
    )


def ask(con: duckdb.DuckDBPyConnection, question: str, provider: Provider) -> dict[str, Any]:
    question = question.strip()
    calls: list[dict[str, Any]] = []

    # 1-2. Question to validated spec, with one correction round.
    messages = [Message("user", prompts.interpret_message(con, question))]
    first = _call(con, provider, "interpret", prompts.INTERPRET_SYSTEM, messages, "json", calls)
    if first is None:
        return _unavailable(question, calls)
    reply, problem = _parse(con, first.text)
    model, corrected = first.model, False
    if problem is not None:
        messages = [
            *messages,
            Message("model", first.text),
            Message("user", prompts.correction_message(problem)),
        ]
        second = _call(
            con, provider, "interpret_retry", prompts.INTERPRET_SYSTEM, messages, "json", calls
        )
        if second is None:
            return _declined(question, calls, _rejection_text(problem))
        reply, problem = _parse(con, second.text)
        model, corrected = second.model, True
        if problem is not None or reply is None:
            return _declined(question, calls, _rejection_text(problem or {"detail": "no reply"}))

    if isinstance(reply, _RefuseReply):
        # A refusal is prose too: any figure in it must come from the catalogue.
        allowed = numbers.collect([prompts.registry_payload(con)])
        limitation = reply.limitation.strip()
        if numbers.unsupported(limitation, allowed):
            limitation = GENERIC_REFUSAL
        return _declined(question, calls, limitation, answer_source="model")

    spec = reply.spec  # type: ignore[union-attr]  # a refusal returned above

    # 3. Execute. Nothing the model wrote reaches the database except this spec.
    result = semantic.run_query(con, spec)
    context = result["applied_context"]
    rows = result["rows"]
    period = _period_text(spec, rows)
    interpretation = _interpretation(spec, context, period, corrected, model)
    described = {
        "interpretation": interpretation,
        "query_spec": spec.model_dump(by_alias=True, exclude_none=True),
        "applied_filters": context["filters"],
        "period": period,
    }
    if not rows:
        spans = semantic.coverage(con).get(spec.metric, {})
        covered = "; ".join(f"{grain}: {years}" for grain, years in spans.items())
        scope = _scope_text(context["filters"]) or "this selection"
        return _declined(
            question,
            calls,
            f"No rows match {scope}"
            + (f" for {period}" if period else "")
            + f". {context['metric_label']} covers {covered}.",
            **described,
        )

    records = semantic.run_records(con, spec, limit=RECORDS_PREVIEW)

    # 4-5. Rows to prose, post-validated; a template if the prose will not validate.
    payload = {
        "question": question,
        "metric": context["metric_label"],
        "unit": context["unit"],
        "filters": [
            f"{item['dimension_label']}: {', '.join(item['values_display'])}"
            for item in context["filters"]
        ],
        "period": period,
        "rows": _model_rows(spec, rows),
        "caveats": [caveat["message"] for caveat in result["caveats"]],
    }
    allowed = numbers.collect(
        [payload["rows"], payload["filters"], payload["period"], payload["caveats"]]
    )
    answer, source = None, "template"
    messages = [Message("user", prompts.answer_message(payload))]
    for purpose in ("answer", "answer_retry"):
        completion = _call(con, provider, purpose, prompts.ANSWER_SYSTEM, messages, "text", calls)
        if completion is None:
            break
        text = completion.text.strip()
        bad = numbers.unsupported(text, allowed)
        if not bad:
            answer, source = text, "model"
            break
        messages = [
            *messages,
            Message("model", completion.text),
            Message("user", prompts.number_correction_message(bad)),
        ]
    if answer is None:
        answer = template_answer(spec, rows, context)
        # Built from the rows, so this cannot fail; checked anyway, because an
        # unvalidated number must never be shown.
        if numbers.unsupported(answer, numbers.collect([rows, context["filters"]])):
            raise RuntimeError("template answer quoted a number not in its rows")

    return {
        **_base(question, calls),
        **described,
        "status": "answered",
        "answer": answer,
        "answer_source": source,
        "chart_spec": _chart(spec, rows, context),
        "source_datasets": context["source_datasets"],
        "rows": rows,
        "records_preview": records["records"],
        "records_total": records["total_matching"],
        "caveats": result["caveats"],
        "applied_context": context,
        "data_origin": context["data_origin"],
        "grain_source": context["grain_source"],
        "provenance_notes": context["provenance_notes"],
    }


def starter_questions() -> list[dict[str, str]]:
    return [{"question_id": s.question_id, "question": s.question} for s in STARTERS]
