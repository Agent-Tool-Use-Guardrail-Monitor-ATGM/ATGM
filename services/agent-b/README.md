# Agent B

Agent B, aka Email Emilio is an email-drafting assistant with the following tools:
- `tone_checker`, that checks whether the email's format adheres to the requested (or default) format, and 
- `sensitive_content_scan`, that scans the email's content for sensitive data, like passwords, or JWT tokens,
and alerts the user if any sensitive data was found.

## Use in local environment

### Setup local environment

```
.../ATGM/services/agent-b/src/agent_b$ uv sync
```

Download Ollama from its [website](https://ollama.com/download)

```
$ ollama pull qwen2.5:7b # or qwen2.5:1.5b, if there's not enough memory for qwen2.5:7b
--> then code should be adjusted in llm_client.py too
```

### Run in local environment

For python environment choose `ATGM/services/agent-b/.venv/bin/python3`.

Run the agent with:

```
.../ATGM/services/agent-b/src/agent_b$ python3 main.py
```

### Run tests in local environment

```
.../ATGM/services/agent-b/src/agent_b PYTHONPATH=src uv run pytest tests/ -v
```

Note: it might take a few minutes.


## Project Integration

**Publishes to:** `tool-calls.B`

Event format: see the agent event schema (Teams chat).

Suggested layout (ports & adapters):

```
domain/     agent logic and tools; no Kafka/DB imports
adapters/   Kafka publisher, LLM client, database
main.py     wires domain + adapters, reads config from environment variables
Dockerfile
```


**Owners:** Fanni, Ági
