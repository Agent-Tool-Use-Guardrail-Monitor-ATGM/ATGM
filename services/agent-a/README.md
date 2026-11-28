# Agent A (DataLens)

Agent A is DataLens, a statistics agent built by Maxim and Asmar. It lives in five repositories
next to this one (clone them into the same parent folder):

| Repository | What it is |
| --- | --- |
| [datalens-identity](https://github.com/Agent-Tool-Use-Guardrail-Monitor-ATGM/datalens-identity) | Keycloak realm `datalens` (login, users, roles) |
| [datalens-messaging](https://github.com/Agent-Tool-Use-Guardrail-Monitor-ATGM/datalens-messaging) | RabbitMQ for identity events |
| [datalens-agent](https://github.com/Agent-Tool-Use-Guardrail-Monitor-ATGM/datalens-agent) | The agent: API, worker, tool policy, outbox and Kafka publisher |
| [datalens-web](https://github.com/Agent-Tool-Use-Guardrail-Monitor-ATGM/datalens-web) | The web frontend |
| [datalens-collector](https://github.com/Agent-Tool-Use-Guardrail-Monitor-ATGM/datalens-collector) | Runs experiment sessions and exports them as JSONL (see its `COMMANDS.md`) |

## How its events reach ATGM

```
agent-worker -> outbox (agent-postgres) -> agent-publisher -> agent.events.v1
             -> agent-a-adapter (this repo) -> tool-calls.A -> S01 ... S10, storage sink
```

DataLens never writes to `tool-calls.A` itself. The [adapter](../agent-a-adapter/README.md) translates
its events into the ATGM event schema.

## Two ways to feed Agent A into the pipeline

**1. Replay recorded sessions (no LLM, no login).** This is the default for demos and experiments,
and the fallback when the Groq quota runs out:

```
docker compose up -d                                   # ATGM stack
python -m agent_a_adapter.replay all-events.jsonl --delay 0.5 --max-sessions 50
```

**2. Run DataLens live.** Order matters:

1. ATGM: `docker compose up -d` (creates the `atgm` network and Kafka).
2. `datalens-identity` and `datalens-messaging`: follow their READMEs (Keycloak realm, RabbitMQ).
3. `datalens-agent`: copy `.env.example` to `.env`, fill it in, then
   `docker compose -f compose.yaml -f compose.runtime.yaml -f compose.atgm.yaml up -d`.
   `compose.atgm.yaml` adds the publisher, which joins the `atgm` network and writes to `kafka:9092`.
4. `datalens-web`: log in through the `datalens` realm and ask a question.
5. Check: `docker compose logs -f agent-a-adapter` here should show the new session.

## What the monitor can and cannot see

- **Tool level only.** Events carry tool names, policy decisions and argument *features*, not raw
  arguments or answer text (privacy by design). A prompt injection that only changes the final answer,
  without an unusual tool call, looks normal to every detector. In the recordings, 29 of the 57 injected
  sessions look like ordinary allowed traces.
- **Some calls have no tool name.** When the model fails before choosing a tool, the event has no
  name; the adapter keeps it as tool `unknown`.
- **Labels describe outcomes.** `model_failure`, `policy_blocked`, `answer_violation` and
  `tool_trace_allowed` say what happened, not what the scenario intended. B1 counts
  `policy_blocked` and `answer_violation` as violations and leaves `model_failure` runs out of training.
