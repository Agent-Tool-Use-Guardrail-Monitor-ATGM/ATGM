"""Ground truth in PostgreSQL (scenario_db), the same table the scenario generator writes.

The mock agents use the session id as scenario_id, so the review queue can look up
whether a session was an attack.
"""
from __future__ import annotations

import os

import psycopg
from psycopg.types.json import Jsonb

from atgm_mocks.domain.sessions import Session

_DDL = """
CREATE TABLE IF NOT EXISTS ground_truth (
    scenario_id       TEXT PRIMARY KEY,
    agent             TEXT NOT NULL,
    category          TEXT NOT NULL CHECK (category IN ('normal', 'adversarial')),
    attack_type       TEXT,
    expected_tools    JSONB NOT NULL,
    expected_behavior TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
)"""


class GroundTruthStore:
    def __init__(self) -> None:
        env = os.environ.get
        self._conn = psycopg.connect(host=env("DB_HOST", "localhost"), port=int(env("DB_PORT", "5432")),
                                     dbname=env("DB_NAME", "scenario_db"), user=env("DB_USER", "scenario_svc"),
                                     password=env("DB_PASSWORD", ""), autocommit=True)
        self._conn.execute(_DDL)

    def save(self, s: Session) -> None:
        self._conn.execute(
            "INSERT INTO ground_truth (scenario_id, agent, category, attack_type, expected_tools, "
            "expected_behavior) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (scenario_id) DO NOTHING",
            (s.session_id, s.agent, s.category, s.attack_type, Jsonb(s.expected_tools), s.expected_behavior))
