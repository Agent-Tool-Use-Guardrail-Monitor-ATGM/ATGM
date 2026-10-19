# Scenario generator (placeholder)

**Owner:** Áron

Plays the user: sends normal and attack tasks to Agent A and Agent B, records the ground truth (which sessions are attacks) in `scenario_db`, and announces tool roll-outs on `toolset-config`.

**Open question:** how a run is started on an agent (Kafka command topic or HTTP endpoint). This needs agreement with both agent teams.

Suggested layout (ports & adapters):

```
domain/     task templates, attack injection, scenario schedule
adapters/   agent client (HTTP or Kafka), Kafka publisher, ground-truth store (PostgreSQL)
main.py
Dockerfile
```
