# OISS PoC — build handoff prompts

Task prompts for building the DE&S Odisha statistical-data PoC with a coding assistant. Each is self-contained:
paste `00_project_context.md` first, then the task file. Any capable coding assistant can run these.

| File | What it covers | RFP areas |
|---|---|---|
| `00_project_context.md` | Shared context — project, stack, data, rules. Prepend to every task. | — |
| `claude_code_prompt_1_data_layer.md` | Canonical schema, loaders, validation, reconciliation checks | 1, 2 (backend) |
| `claude_code_prompt_2_semantic_layer.md` | Fix-ups, metric/dimension registry, query spec, caveats, narrative facts | 3–5 (foundation) |
| `claude_code_prompt_3_frontend_ingestion.md` | React foundation, ingest + lineage screens (implements `web/DESIGN.md`) | 1, 2 |
| `claude_code_prompt_4_dashboard.md` | Price and agriculture dashboards, drill-down | 3 |
| `claude_code_prompt_5_exports.md` | Export service: CSV, Excel, PDF, JSON, chart image, with applied context | 8 |
| `claude_code_prompt_6_genai.md` | Grounded narrative and conversational assistant | 4, 5 |
| `claude_code_prompt_7_sandbox.md` | Model-service adapter and guided sandbox | 6, 7 |
| `claude_code_prompt_8_integration_demo.md` | Integration, hardening, demo script, documentation | all |

`web/DESIGN.md` is the house style — palette, typography, density, provenance badges, chart conventions. Task 3
implements it; tasks 4, 6 and 7 follow it. Keep it in the repo at `web/DESIGN.md`.

**Order matters.** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. Exports (5) sit before GenAI and the sandbox deliberately, so each
later module plugs into one export path. Tasks 6 and 7 are independent of each other and can be swapped or run in
parallel; 8 needs everything.

Two rules that run through all of them: **provenance propagates end to end** (`data_origin`, `annual_level_basis`,
`grain_source`, caveats, dataset versions), and **the LLM never computes a number or writes SQL**.
