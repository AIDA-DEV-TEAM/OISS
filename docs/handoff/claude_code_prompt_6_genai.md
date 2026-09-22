# Task 6 — GenAI dashboard explanation and conversational assistant (RFP areas 4 and 5)

Read `00_project_context.md` first. Requires the semantic layer (task 2), dashboard (task 4) and exports (task 5).

This is where a demo in front of a statistics directorate is won or lost. **The model must not compute, and must not
be able to compute.** Numbers come from SQL; the model only turns structured facts into sentences or turns a question
into a validated query spec.

## 1. Provider abstraction first

The LLM provider for a state-government bid must be whatever the organisation has approved; do not hard-code one.

- `app/llm/provider.py`: an interface with `complete(system, messages, response_format)` and implementations for at
  least one hosted provider plus a **`CachedProvider`** and a **`FixtureProvider`**.
- Configuration by environment variable: provider, model, API key, timeout.
- **Every call is cached by a hash of its input.** For predefined questions and the standard dashboard views, ship the
  cache so the demo works offline and identically each time. If a live call fails or exceeds its timeout, fall back to
  the cached response and mark the response `served_from_cache`.
- Log every prompt and response to a local table for review. No prompts leave the machine other than to the provider.

## 2. Dashboard narrative (area 4)

```
POST /narrative/dashboard   {query_spec or view_id} -> {narrative, facts_used, caveats, served_from_cache}
```

1. Call `POST /query/narrative-facts` — totals, period-on-period movement, leading and lagging districts, largest
   changes, anomalies, caveats. Pure SQL.
2. Hand that JSON to the model with a system prompt that says: **use only these numbers, quote them exactly, do not
   calculate anything new, do not add context you were not given, state every caveat supplied.**
3. **Validate the output before returning it**: every number in the narrative must appear in the fact bundle
   (compare normalised numeric tokens). If one does not, retry once, then fall back to a deterministic
   template-rendered summary. Never show an unvalidated number.
4. The narrative must state the relevant caveats in plain language — synthetic data, projected levels, MSP
   substitution, block aggregation.

## 3. Conversational assistant (area 5)

```
POST /assistant/ask   {question, context?} -> {answer, chart_spec, query_spec, applied_filters, source_datasets,
                                               period, records_preview, caveats, served_from_cache}
```

1. The model receives the **registry** (metrics, dimensions, allowed values) and the question, and returns **only a
   query spec** as JSON — never SQL, never an answer with numbers in it.
2. The backend validates the spec against the registry. On a 422, return the error to the model once for a corrected
   spec; then give up gracefully with a message saying what it could not answer.
3. Execute the spec. Pass the **result rows** back to the model for a one-paragraph answer, under the same
   no-new-numbers rule and the same post-validation as the narrative.
4. Return everything the RFP asks for alongside the answer: the applied filters, the source dataset, the reporting
   period, a relevant chart and the supporting records.

**Ship a set of predefined questions** (the RFP says the demo asks predefined natural-language questions) with cached
responses, covering: a district comparison, a trend over time, a leading/lagging question, a farm-harvest vs
wholesale question, a question that must return a caveat (paddy prices → MSP), and one the system should decline
because the data does not support it.

## 4. Refusals are a feature

If the question needs data that does not exist (prices after 2018-19 that are official, block-level prices, a crop
that is not priced in that district), the assistant says so and names the limitation. A system that declines
accurately reads as more trustworthy than one that always answers.

## 5. Tests

- Fact-bundle numbers appear verbatim in the narrative; an injected wrong number fails validation.
- A question mapping to a known query returns the expected figure (assert one exact value).
- A question requiring an unavailable dimension returns a graceful refusal, not a guess.
- Cache hit returns identical bytes and sets `served_from_cache`.
- Provider outage (simulated) still returns a usable answer from cache or template.
- The model never receives raw table names or SQL, and no code path lets model output reach the database directly.
