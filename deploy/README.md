# Deployment targets

The whole system is defined once in the root `docker-compose.yml`. This folder only holds the ways to run it somewhere other than a laptop.

| Folder | Target | Status |
|---|---|---|
| `azure/` | one Azure VM running the Docker Compose stack, scripted with the Azure CLI and cloud-init | ✅ tested (UK South, Standard_B2ms) |
| `k8s/` | Kubernetes manifests | stretch goal, not started |

Platform configuration that the containers themselves use (Kafka topics, database setup, Grafana) lives in `infra/`, not here.
