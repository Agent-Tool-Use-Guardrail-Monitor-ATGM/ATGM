# S07: allow-list policy check

**Owner:** Agnes · **Pipeline:** P1 (allow-list check) · **Status:** not started

**Paper:** OWASP Top 10 for LLM Applications 2025 (LLM06: Excessive Agency); Zhao et al., *ClawGuard*, arXiv 2026.

**Task:** Check every tool call in real time against hard rules: is the tool allowed for this agent, are the arguments within limits (e.g. no secrets, bounded column counts)? Agent B's "only permitted tools are called" test is a good starting point.

| | |
|---|---|
| **Reads** | `tool-calls.A`, `tool-calls.B`; `toolset-config` (the current allowed tools per agent) |
| **Publishes** | `violation.flagged` on `flags` (detector `allow_list`, `rule`, `severity`). Hard rule: never overridden by drift. |
| **Connects to** | S03 counts these violations; ACI and dashboards. |

See `../README.md` for the message formats and the layout. `s04-online-forest/` is a complete example of a stage that reads tool calls and publishes scores.
