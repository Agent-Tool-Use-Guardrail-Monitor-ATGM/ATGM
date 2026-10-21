# Agent B (placeholder)

**Owners:** Fanni, Ági · **Tools:**  `email_draft` · **Publishes to:** `tool-calls.B`

Event format: see the agent event schema (Teams chat).

Suggested layout (ports & adapters):

```
domain/     agent logic and tools; no Kafka/DB imports
adapters/   Kafka publisher, LLM client, database
main.py     wires domain + adapters, reads config from environment variables
Dockerfile
```
a