# Zero-cost agent capability plan

This repository is a Telegram-first personal agent, not a full Hermes Agent clone. Capability availability depends on the configured Gemini model, Telegram's supported media formats, free-tier quotas, and connected service credentials.

## Implemented or present in the repository

| Area | Current status | Notes |
| --- | --- | --- |
| Tool-using agent loop | Present | Bounded to six model steps and twelve tool calls per run. |
| Public web research | Present | Search, open, same-site crawl, bounded concurrent multi-query research, and user-scoped conversation search; public search endpoints can fail or rate-limit. |
| Conversation context | Present | Recent messages persisted in PostgreSQL. |
| Explicit saved memory | Present | User-scoped memory commands and memory context. |
| Tasks and reminders | Present | PostgreSQL-backed; reminder delivery reliability depends on the worker/runtime. |
| Recurring jobs | Partial | Daily/weekly jobs with pause/resume/edit/cancel and a GitHub Actions worker exist. End-to-end delivery still needs live verification; one-shot modes are not implemented. |
| Multimodal input | Partial | Image/audio/video/PDF and supported documents are forwarded when accepted by the configured model; not all formats are guaranteed. |
| Built-in coaching skills | Present | French, vegetarian cooking, drawing, Buddhist studies, and 鈴鼓. |
| Persistent custom skills | Added in this branch | Owner-only; changes are staged and require explicit approval. |
| GitHub / Render / Todoist / Calendar | Partial | Existing owner-gated tools; credentials and service APIs determine availability. Mutations use approval queue. |
| Bounded runtime policy | Added in this branch | Tool-call limits, bounded tool output, reduced sensitive argument/error logging, and zero-cost instructions. |

## Not equivalent to Hermes yet

- No unrestricted shell/terminal or persistent isolated execution sandbox.
- No general interactive browser automation or desktop/computer control.
- No true isolated child agents/subagent delegation. A bounded parallel read-only analysis helper exists, but it uses the same model quota and is not an isolated subagent.
- No MCP server client or extensible third-party plugin catalog.
- No broad multi-platform messaging gateway beyond the current Telegram entry point.
- No full skill registry installer/security scanner or autonomous background skill curator.
- No robust scheduler lifecycle for pause/resume/edit/one-shot jobs; delivery retries and idempotency need further work.
- No guarantee of unlimited AI use. Gemini and hosting free tiers have quotas and can change.

## Zero-cost policy

No paid fallback model, paid API, subscription, or new billable infrastructure may be added automatically. If a free quota or service is unavailable, the agent should fail clearly rather than switch to a paid option. Do not enable production changes until tests pass and the owner explicitly approves the deployment.

## Validation

The GitHub Actions workflow compiles the runtime modules and runs unit tests. CI success is not proof of a successful Render deployment, working credentials, Telegram delivery, or scheduled-job delivery. Those require separate integration checks.
