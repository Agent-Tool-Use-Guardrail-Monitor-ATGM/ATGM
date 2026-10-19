# Agent A (placeholder)

**Owners:** Maxim, Asmar · **Tools:** `read_file`, `calculator` · **Publishes to:** `tool-calls.A`

Event format: see the agent event schema (Teams chat).

Suggested layout (ports & adapters):

```
domain/     agent logic and tools; no Kafka/DB imports
adapters/   Kafka publisher, LLM client, database
main.py     wires domain + adapters, reads config from environment variables
Dockerfile
```
