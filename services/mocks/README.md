# Mocks: temporary stand-ins

**Owner:** Áron · **Status:** temporary. Each mock is switched off once the real service publishes the same messages.

The pipeline needs tool calls and anomaly scores before the real agents and detectors publish them. These two services produce realistic stand-ins **in the same Kafka topics and message format** as the real ones, so nothing downstream changes when they are replaced.

| Mock | Publishes | Replaced by |
|---|---|---|
| `mock-agents` | tool-call sessions of Agent A and B to `tool-calls.A` / `tool-calls.B`, ground truth to `scenario_db.ground_truth` | Agent A (datalens-agent), Agent B + scenario generator |
| `mock-scorer` | one `anomaly.scored` per tool call and per session end to `scores` (detector `mock_scorer`) | Online Isolation Forest, Markov check, ... |

## Run

```bash
docker compose --profile mocks up -d --build      # platform + DSPOT + the two mocks
docker compose logs -f mock-agents mock-scorer dspot
```

Without `--profile mocks` the mocks do not start. Settings are environment variables in `docker-compose.yml` (rate, warm-up, attack rate, seed); see the docstrings of `run_agents.py` and `run_scorer.py`.

The first 1000 sessions per agent are normal only, so the detectors and DSPOT can calibrate; afterwards 5% of the sessions are attacks. At 5 sessions per second the warm-up takes about 7 minutes.

## What a session looks like

Events use Agent A's envelope (`schema_version "1.0"`, body in `data`): `session.started`, one `tool_call.completed` or `tool_call.failed` per call, `session.ended`. A tool call's `data`:

```json
{"agent_id": "B", "tool_call_id": "…", "tool_name": "tone_checker",
 "arguments": {"draft": "…", "tone": "formal"}, "duration_ms": 27, "success": true,
 "session_call_index": 1, "time_since_previous_call_ms": 1180}
```

These are the fields the Online Isolation Forest reads, here inside `data`.

| Agent | Normal session | Attacks (as in the scenario generator's templates) |
|---|---|---|
| A | `inspect_dataset → describe_columns → 1-3 × aggregate/correlate → finalize_statistics` | `unauthorized_tool` (export_dataset), `unsafe_args` (path traversal, 400 columns), `out_of_order` (no inspection first) |
| B | `tone_checker → sensitive_content_scan`, sometimes twice | `unauthorized_tool` (send_email), `unsafe_args` (password or card number in the draft), `skipped_check` (no checks) |

Labels never appear in events; the ground truth uses the session id as `scenario_id`.

The mock scorer is deliberately simple (rare tool transitions, unusually long arguments, secret-looking arguments, failures, unusual session length) and learns from everything it sees. It is not one of the project's stream mining algorithms.

## Tests

```bash
cd services/mocks
pip install -e ".[test]"
pytest
```
