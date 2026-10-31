# ATGM: Agent Tool-Use Guardrail Monitor

Two LLM agents send every tool call to Kafka. Stream processing services check the calls live, results are stored in PostgreSQL, and Grafana shows them. The design is in [architecture_and_team_work_plan.md](architecture_and_team_work_plan.md).

## Run the platform

Needs Docker Desktop.

```bash
cp .env.example .env        # first time only: set your own passwords in .env (never committed)
docker compose up -d        # start Kafka, PostgreSQL, Grafana
docker compose down         # stop
docker compose down -v      # stop and delete all data
```

| What | Where |
|---|---|
| Kafka UI | http://localhost:8080 |
| Grafana | http://localhost:3000 (user `admin`, password from `.env`) |
| Kafka | `localhost:29092` from your PC, `kafka:9092` from containers |
| PostgreSQL | `localhost:5432`; each service has its own database (see `infra/postgres/init.sh`) |

## Connecting a service from another repository

The platform runs on a Docker network named `atgm`. A service in a separate repository (for example `datalens-agent`) joins it by adding this to its own compose file, and then reaches Kafka at `kafka:9092`:

```yaml
networks:
  default:
    name: atgm
    external: true
```

Start the ATGM platform first (`docker compose up -d` here), then the other repository's services.

## Repository layout

```
docker-compose.yml          shared platform: Kafka, PostgreSQL, Grafana
infra/                      Kafka topics, database setup, Grafana connection
services/
  agent-a/                  pointer only: Agent A lives in its own repository (see below)
  agent-b/                  Agent B, e-mail drafting agent (Fanni, Ági)
  scenario-generator/       Áron
  stream-processing/        one subfolder per member's algorithms
docs/                       design documents and figures
```

### Team repositories

| Repository | Contents | Owners |
|---|---|---|
| [ATGM](https://github.com/Agent-Tool-Use-Guardrail-Monitor-ATGM/ATGM) (this one) | Shared platform, Agent B, scenario generator, stream processing, docs | all |
| [datalens-agent](https://github.com/Agent-Tool-Use-Guardrail-Monitor-ATGM/datalens-agent) | Agent A, statistics/calculator agent (FastAPI + CrewAI) | Maxim, Asmar |
| [datalens-identity](https://github.com/Agent-Tool-Use-Guardrail-Monitor-ATGM/datalens-identity) | User login (Keycloak) for the agents | Maxim |

Work happens on the `development` branch: create a feature branch from it and open a pull request into `development`.

## Team rules

1. Work in your own `services/` folder. Changes to `infra/` or topic names: tell the team first.
2. Services talk only through Kafka. Don't import another service's code or use another service's database.
3. Keep your algorithm free of Kafka and database code (ports & adapters), so it can be tested and run on datasets.
4. Configuration comes from environment variables. Never commit passwords: they go in `.env`, which is git-ignored.
5. Work on a branch and open a pull request into `main`.

## Decisions

- **One database (PostgreSQL), not PostgreSQL + InfluxDB.** Fewer moving parts, and Grafana reads PostgreSQL directly. Each service gets its own database inside the one server. (we can change this if we decide later)
- **Kubernetes:** possible later (on Azure); everything runs in Docker Compose for now.
