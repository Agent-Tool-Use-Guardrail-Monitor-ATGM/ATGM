# Scenario generator

> **Status:** this was our first scenario generator, built for the Agent B dataset. It was replaced by
> the flow below and is no longer run (not in Docker Compose). The code is kept to show how the
> dataset work started: task templates, calling the agent directly and a ground-truth table.
>
> **Why it was replaced:** the scenarios needed a policy (allowed tools, recipients, date window, call
> order, max calls) so sessions can be labelled by real behaviour and the agent's events needed the
> scenario ID as session ID. The current Agent B and the mock scenario builder do both.

## Current flow (Agent B dataset)

`export_scenarios.py` (services/mocks) → `main.py --prompt` (Agent B) → `label_events.py` → `load_ground_truth.py` → `event_publisher.py` (replay into Kafka)

Files end up in `dataset/agent_b/` (`scenarios/`, `events/`, `labels/`). See `dataset/agent_b/README.md`.

## Original README

Plays the user: sends normal and attack tasks to Agent A and Agent B, records the ground truth (which sessions are attacks) in `scenario_db`, and announces tool roll-outs on `toolset-config`.

**Open question:** how a run is started on an agent (Kafka command topic or HTTP endpoint). This needs agreement with both agent teams.

Suggested layout (ports & adapters):

```
domain/     task templates, attack injection, scenario schedule
adapters/   agent client (HTTP or Kafka), Kafka publisher, ground-truth store (PostgreSQL)
main.py
Dockerfile
```
