"""ATGM review UI (Streamlit): streamlit run src/review_ui/app.py

Lists the sessions ACI sent to review that nobody has judged yet, shows what happened in each
(tool calls, detector scores, rule flags, DSPOT alarms, ACI's decision), and publishes the
reviewer's verdict to the `labels` topic. Reads analytics_db (read-only) and scenario_db
(only to hide sessions the simulated reviewer answers).

Environment: KAFKA_BOOTSTRAP [localhost:29092]  LABELS_TOPIC [labels]
             DB_HOST [localhost]  DB_PORT [5432]  DB_PASSWORD
             ANALYTICS_DB [analytics_db] / ANALYTICS_USER [analytics_svc]
             SCENARIO_DB [scenario_db] / SCENARIO_USER [scenario_svc]
"""
from __future__ import annotations

import json
import os

import pandas as pd
import psycopg
import streamlit as st
from psycopg.rows import dict_row

from review_ui import domain

env = os.environ.get
st.set_page_config(page_title="ATGM review", layout="wide")


@st.cache_resource
def db(name: str, user: str):
    return psycopg.connect(host=env("DB_HOST", "localhost"), port=int(env("DB_PORT", "5432")), dbname=name,
                           user=user, password=env("DB_PASSWORD", ""), autocommit=True,
                           options="-c default_transaction_read_only=on", row_factory=dict_row)


def query(sql: str, **params) -> list[dict]:
    try:
        return db(env("ANALYTICS_DB", "analytics_db"), env("ANALYTICS_USER", "analytics_svc")).execute(sql, params).fetchall()
    except psycopg.errors.UndefinedTable:          # the storage sink has not created its tables yet
        return []


def with_ground_truth(session_ids: list[str]) -> set[str]:
    if not session_ids:
        return set()
    try:
        conn = db(env("SCENARIO_DB", "scenario_db"), env("SCENARIO_USER", "scenario_svc"))
        rows = conn.execute("SELECT scenario_id FROM ground_truth WHERE scenario_id = ANY(%s)", (session_ids,))
        return {r["scenario_id"] for r in rows}
    except (psycopg.Error, OSError):               # no ground truth table (no mocks ran): nothing to hide
        return set()


@st.cache_resource
def producer():
    from confluent_kafka import Producer
    return Producer({"bootstrap.servers": env("KAFKA_BOOTSTRAP", "localhost:29092"), "acks": "all"})


def publish(event: dict) -> str | None:
    """Send the label; None on success, else the error text."""
    errors: list = []
    producer().produce(env("LABELS_TOPIC", "labels"), key=event["data"].get("agent_id") or "",
                       value=json.dumps(event), on_delivery=lambda err, _msg: errors.append(err))
    if producer().flush(10) or errors != [None]:
        return f"Kafka did not confirm the label ({errors or 'timeout'})"
    return None


# ---------- sidebar ----------
st.sidebar.title("ATGM review")
reviewer = st.sidebar.text_input("Your name", value=st.session_state.get("reviewer", ""), key="reviewer")
show_simulated = st.sidebar.checkbox("Also show sessions the simulated reviewer answers", value=False)
agents = st.sidebar.multiselect("Agents", ["A", "B"], default=["A", "B"])
if st.sidebar.button("Refresh"):
    st.rerun()
done = st.session_state.setdefault("done", set())            # labelled here, until the sink stores them

# ---------- queue ----------
items = [domain.item_from_decision(r) for r in query(domain.PENDING_SQL, limit=500)]
items = [i for i in items if i["session_id"] not in done and (i["agent_id"] in agents or i["agent_id"] is None)]
if not show_simulated:
    items = domain.without_ground_truth(items, with_ground_truth([i["session_id"] for i in items]))

counts = {r["reviewer"]: r["count"] for r in query(domain.COUNTS_SQL)}
c1, c2, c3 = st.columns(3)
c1.metric("Waiting for review", len(items))
c2.metric("Labelled by humans", counts.get("human", 0))
c3.metric("Labelled by the simulated reviewer", counts.get("simulated", 0))

if not items:
    st.info("Nothing to review. Sessions appear here when ACI decides “review” or picks them for a random audit.")
    st.stop()

queue = pd.DataFrame([{"decided": i["decided_at"], "agent": i["agent_id"], "session": i["session_id"],
                       "ACI": i["decision"], "audit": i["audit"], "session score": i["session_score"]}
                      for i in items])
st.subheader("Queue")
st.caption("Newest first. Audits are random samples: review them like any other session.")
pick = st.dataframe(queue, hide_index=True, width="stretch", on_select="rerun",
                    selection_mode="single-row", height=min(38 + 35 * len(queue), 400))
row = pick.selection.rows[0] if pick.selection.rows else 0
item = items[row]
sid = item["session_id"]

# ---------- session details ----------
st.subheader(f"Session {sid}")
d1, d2, d3, d4 = st.columns(4)
d1.metric("Agent", item["agent_id"] or "?")
d2.metric("ACI decision", f"{item['decision']}{' (audit)' if item['audit'] else ''}")
d3.metric("Session score", "-" if item["session_score"] is None else f"{item['session_score']:.3f}")
d4.metric("Pass up to / flag from",
          f"{item['pass_up_to'] if item['pass_up_to'] is not None else '-'} / "
          f"{item['flag_from'] if item['flag_from'] is not None else '-'}")

calls = query(domain.CALLS_SQL, sid=sid)
st.markdown("**Tool calls**")
if calls:
    st.dataframe(pd.DataFrame([{**c, "arguments": json.dumps(c["arguments"]) if c["arguments"] else ""}
                               for c in calls]), hide_index=True, width="stretch")
else:
    st.caption("No tool calls stored for this session.")

left, right = st.columns(2)
with left:
    st.markdown("**Detector scores**")
    scores = query(domain.SCORES_SQL, sid=sid)
    if scores:
        st.dataframe(pd.DataFrame(scores), hide_index=True, width="stretch")
    else:
        st.caption("None")
with right:
    st.markdown("**Rule flags and DSPOT alarms**")
    flags, alarms = query(domain.FLAGS_SQL, sid=sid), query(domain.ALARMS_SQL, sid=sid)
    if flags:
        st.dataframe(pd.DataFrame(flags), hide_index=True, width="stretch")
    if alarms:
        st.dataframe(pd.DataFrame(alarms), hide_index=True, width="stretch")
    if not flags and not alarms:
        st.caption("None")

# ---------- verdict ----------
st.subheader("Your verdict")
with st.form(f"verdict-{sid}", clear_on_submit=True):
    verdict = st.radio("Was this session an attack?", list(domain.VERDICTS), horizontal=True, index=None)
    vtype = st.selectbox("Violation type (attacks only)", domain.VIOLATION_TYPES, index=None,
                         placeholder="Choose for an attack")
    if st.form_submit_button("Submit verdict", type="primary"):
        if verdict is None:
            st.error("Choose Attack or Normal.")
        elif domain.VERDICTS[verdict] == "attack" and vtype is None:
            st.error("Choose a violation type for an attack.")
        else:
            event = domain.label_event(item, domain.VERDICTS[verdict], vtype, reviewer)
            error = publish(event)
            if error:
                st.error(error)
            else:
                done.add(sid)
                st.toast(f"Labelled {sid} as {event['data']['verdict']}")
                st.rerun()

with st.expander("Recently labelled"):
    st.dataframe(pd.DataFrame(query(domain.DONE_SQL, limit=50)), hide_index=True, width="stretch")
