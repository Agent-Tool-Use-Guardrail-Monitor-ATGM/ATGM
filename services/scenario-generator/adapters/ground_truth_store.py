import os
from pathlib import Path
from typing import TypedDict
import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from domain.task_templates import GroundTruthRecord

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

VALID_CATEGORIES = {"normal", "adversarial"}


class GroundTruthStore:
    """PostgreSQL-backed store for scenario ground truth.

    Labels live ONLY here. They are never sent to the agents or to Kafka.
    """

    def __init__(self) -> None:
        self._connection_params = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", "5432")),
            "dbname": os.getenv("DB_NAME", "scenario_db"),
            "user": os.getenv("DB_USER", "postgres"),
            "password": os.getenv("DB_PASSWORD", ""),
        }
        self._initialize_table()

    def _connect(self):
        return psycopg.connect(**self._connection_params)

    def _initialize_table(self) -> None:
        with self._connect() as   conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ground_truth (
                    scenario_id       TEXT PRIMARY KEY,
                    agent             TEXT NOT NULL,
                    category          TEXT NOT NULL
                                      CHECK (category IN ('normal', 'adversarial')),
                    attack_type       TEXT,
                    expected_tools    JSONB NOT NULL,
                    expected_behavior TEXT NOT NULL,
                    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

    def save(self, record: GroundTruthRecord) -> None:
        if not record["scenario_id"].strip():
            raise ValueError("scenario_id cannot be empty.")

        if record["category"] not in VALID_CATEGORIES:
            raise ValueError("Invalid scenario category.")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ground_truth
                    (scenario_id, agent, category, attack_type,
                     expected_tools, expected_behavior)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    record["scenario_id"],
                    record["agent"],
                    record["category"],
                    record["attack_type"],
                    Jsonb(record["expected_tools"]),
                    record["expected_behavior"],
                ),
            )

    def get(self, scenario_id: str) -> GroundTruthRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT scenario_id, agent, category, attack_type,
                       expected_tools, expected_behavior
                FROM ground_truth
                WHERE scenario_id = %s
                """,
                (scenario_id,),
            ).fetchone()

        return None if row is None else self._to_record(row)

    def get_all(self) -> list[GroundTruthRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT scenario_id, agent, category, attack_type,
                       expected_tools, expected_behavior
                FROM ground_truth
                ORDER BY created_at
                """
            ).fetchall()

        return [self._to_record(row) for row in rows]

    @staticmethod
    def _to_record(row) -> GroundTruthRecord:
        return {
            "scenario_id": row[0],
            "agent": row[1],
            "category": row[2],
            "attack_type": row[3],
            "expected_tools": row[4],  # JSONB comes back as a Python list
            "expected_behavior": row[5],
        }
class ScenarioResultRecord(TypedDict):
    scenario_id: str
    called_tools: list[str]
    tool_outputs: list[dict]
    final_response: str
    execution_status: str
    error_message: str | None


class ScenarioResultStore:
    """PostgreSQL-backed store for actual agent execution results."""

    def __init__(self) -> None:
        self._connection_params = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", "5432")),
            "dbname": os.getenv("DB_NAME", "scenario_db"),
            "user": os.getenv("DB_USER", "postgres"),
            "password": os.getenv("DB_PASSWORD", ""),
        }
        self._initialize_table()

    def _connect(self):
        return psycopg.connect(**self._connection_params)

    def _initialize_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scenario_results (
                    scenario_id TEXT PRIMARY KEY
                        REFERENCES ground_truth(scenario_id),
                    called_tools JSONB NOT NULL DEFAULT '[]'::jsonb,
                    tool_outputs JSONB NOT NULL DEFAULT '[]'::jsonb,
                    final_response TEXT NOT NULL DEFAULT '',
                    execution_status TEXT NOT NULL
                        CHECK (execution_status IN ('success', 'failed')),
                    error_message TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

    def save(self, record: ScenarioResultRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scenario_results (
                    scenario_id, called_tools, tool_outputs,
                    final_response, execution_status, error_message
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (scenario_id) DO UPDATE SET
                    called_tools = EXCLUDED.called_tools,
                    tool_outputs = EXCLUDED.tool_outputs,
                    final_response = EXCLUDED.final_response,
                    execution_status = EXCLUDED.execution_status,
                    error_message = EXCLUDED.error_message,
                    created_at = now()
                """,
                (
                    record["scenario_id"],
                    Jsonb(record["called_tools"]),
                    Jsonb(record["tool_outputs"]),
                    record["final_response"],
                    record["execution_status"],
                    record["error_message"],
                ),
            )