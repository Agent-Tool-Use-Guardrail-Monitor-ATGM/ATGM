# S07: allow-list policy check

Pipeline: Real-time allow-list policy check on each tool call.

Vulnerability: indirect prompt injection. Adversaries might embed malicious instruction within tool-returned content. [2]

Mitigation: enforce rule set at every tool-call boundary, intercept adversarial tool calls that would produce unwanted real-world effect.

**Task:** Check every tool call in real time against hard rules: is the tool allowed for this agent, are the arguments within limits (e.g. no secrets, bounded column counts)? Agent B's "only permitted tools are called" test is a good starting point.

| | |
|---|---|
| **Reads** | `tool-calls.A`, `tool-calls.B`; `toolset-config` (the current allowed tools per agent) |
| **Publishes** | `violation.flagged` on `flags` (detector `allow_list`, `rule`, `severity`). Hard rule: never overridden by drift. |
| **Connects to** | S03 counts these violations; ACI and dashboards. |

See `../README.md` for the message formats and the layout. `s04-online-forest/` is a complete example of a stage that reads tool calls and publishes scores.

**Citations:**
- [1] [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/), 2025 
    - ASI02: Tool Misuse and Exploitation
    - [LLM06:2025 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)
- [2] Zhao et al., [ClawGuard](https://arxiv.org/pdf/2604.11790), 2026
- [3] Wang et al., [Runtime Policy Enforcement for MCP-Based LLM Agents](https://www.researchgate.net/publication/408199447_Runtime_Policy_Enforcement_for_MCP-Based_LLM_Agents), 2026

Owner: Agnes