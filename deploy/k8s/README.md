# Kubernetes (stretch goal)

**Status:** not started.

The design lists a Kubernetes deployment as a stretch goal. A possible path, once the Compose stack is stable:

- one `Deployment` per service, using the same images as `docker-compose.yml`
- `StatefulSet`s (or managed services) for Kafka and PostgreSQL
- a `Job` per topic-creation and database-setup step (today `kafka-init` and `infra/postgres/init.sh`)
- a `CronJob` per batch job (`services/batch-processing/`)
- secrets from the `.env` values as Kubernetes `Secret`s

Tools such as Kompose can generate a first draft from `docker-compose.yml`.
