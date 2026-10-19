#!/usr/bin/env bash
# One PostgreSQL server, one database + login per service (microservice rule: no shared tables).
# Passwords come from .env. Runs only on the first start with an empty volume;
# after editing: docker compose down -v
set -euo pipefail

for svc in agent_a agent_b scenario monitor analytics; do
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres <<SQL
CREATE ROLE ${svc}_svc LOGIN PASSWORD '${SERVICE_DB_PASSWORD}';
CREATE DATABASE ${svc}_db OWNER ${svc}_svc;
REVOKE ALL ON DATABASE ${svc}_db FROM PUBLIC;
SQL
done

# Grafana: read-only access to analytics_db (dashboard data) only.
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres <<SQL
CREATE ROLE grafana_ro LOGIN PASSWORD '${GRAFANA_DB_PASSWORD}';
GRANT CONNECT ON DATABASE analytics_db TO grafana_ro;
\connect analytics_db
GRANT USAGE ON SCHEMA public TO grafana_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE analytics_svc IN SCHEMA public GRANT SELECT ON TABLES TO grafana_ro;
SQL
