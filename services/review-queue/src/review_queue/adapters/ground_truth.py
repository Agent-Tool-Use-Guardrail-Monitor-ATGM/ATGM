"""Read-only ground-truth lookup in scenario_db (written by the scenario generator / mock agents)."""
from __future__ import annotations

import os

import psycopg

from review_queue.domain.queue import Truth


class GroundTruthLookup:
    def __init__(self) -> None:
        env = os.environ.get
        self._conn = psycopg.connect(host=env("DB_HOST", "localhost"), port=int(env("DB_PORT", "5432")),
                                     dbname=env("DB_NAME", "scenario_db"), user=env("DB_USER", "scenario_svc"),
                                     password=env("DB_PASSWORD", ""), autocommit=True)

    def __call__(self, session_id: str) -> Truth | None:
        try:
            row = self._conn.execute(
                "SELECT category, attack_type FROM ground_truth WHERE scenario_id = %s", (session_id,)
            ).fetchone()
        except psycopg.errors.UndefinedTable:      # nothing has written ground truth yet
            return None
        return None if row is None else Truth(row[0], row[1])
