import random

import pytest

from aci.domain.triage import ConformalTriage
from aci.service import ACIService


class FakeSink:
    def __init__(self):
        self.sent = []

    def send(self, topic, key, value):
        self.sent.append((topic, key, value))

    def on(self, topic):
        return [v for t, _, v in self.sent if t == topic]


def score(sid, value, detector="mock_scorer", agent="B"):
    return {"event_type": "anomaly.scored", "session_id": sid, "event_id": f"sc-{sid}-{value}",
            "data": {"agent_id": agent, "detector": detector, "score": value}}


def ended(sid, agent="B"):
    return {"event_type": "session.ended", "session_id": sid, "event_id": f"end-{sid}", "run_id": "run-1",
            "data": {"agent_id": agent, "call_count": 2}}


def label(sid, verdict):
    return {"event_type": "review.labelled", "session_id": sid,
            "data": {"scored_event_id": f"end-{sid}", "detector": "aci", "verdict": verdict}}


def service(audit_rate=0.0, **kw):
    return ACIService(ConformalTriage(bound=20), FakeSink(), {"mock_scorer"}, audit_rate=audit_rate,
                      grace=2.0, rng=random.Random(0), **kw)


def test_decides_after_the_grace_period_with_the_session_maximum():
    svc = service()
    svc.handle(score("s1", 1.0), now=0)
    svc.handle(ended("s1"), now=1)
    svc.handle(score("s1", 4.5), now=2)                     # late score of the session end
    svc.handle(score("s1", 99, detector="other"), now=2)    # other detectors are ignored
    assert svc.tick(2.9) == 0
    assert svc.tick(3.0) == 1
    [d] = svc.sink.on("flags")
    assert d["event_type"] == "decision.made" and d["session_id"] == "s1" and d["run_id"] == "run-1"
    data = d["data"]
    assert data["session_score"] == 4.5 and data["detector"] == "aci" and data["scored_event_id"] == "end-s1"
    assert data["decision"] == "review" and data["prediction_set"] == []        # safe start
    assert svc.sink.on("review-queue") == [d]


def test_learns_only_from_audited_sessions():
    svc = service(audit_rate=1.0)
    svc.handle(score("s1", 1.0), now=0)
    svc.handle(ended("s1"), now=0)
    svc.tick(5)
    assert svc.sink.on("review-queue")[0]["data"]["audit"] is True
    svc.handle(label("s1", "false_alarm"), now=6)
    assert svc.counts.learned == 1 and svc.triage.trackers["B"][0].t == 1
    svc.handle(label("s1", "false_alarm"), now=7)          # answered once only
    svc.handle(label("unknown", "attack"), now=7)
    assert svc.counts.learned == 1

    plain = service(audit_rate=0.0)
    plain.handle(ended("s2"), now=0)
    plain.tick(5)
    plain.handle(label("s2", "attack"), now=6)              # a review, not an audit: not learned
    assert plain.counts.learned == 0


def test_dspot_labels_are_ignored():
    svc = service(audit_rate=1.0)
    svc.handle(ended("s1"), now=0)
    svc.tick(5)
    svc.handle({**label("s1", "attack"), "data": {"detector": "mock_scorer", "verdict": "attack"}}, now=6)
    assert svc.counts.learned == 0


def test_pass_and_flag_go_only_to_flags_unless_audited():
    svc = service(audit_rate=0.0)
    c, v = svc.triage._pair("B")
    c.q, v.q = 3.0, 14.0                                     # pass up to 3, flag from 6
    for sid, value in (("low", 1.0), ("high", 9.0)):
        svc.handle(score(sid, value), now=0)
        svc.handle(ended(sid), now=0)
    svc.tick(5)
    assert sorted(d["data"]["decision"] for d in svc.sink.on("flags")) == ["flag", "pass"]
    assert svc.sink.on("review-queue") == []


def test_closed_loop_reaches_the_target_rates():
    """Simulated stream: reviewer answers audits immediately; rates measured on all sessions."""
    rng = random.Random(3)
    svc = ACIService(ConformalTriage(alpha_normal=0.05, alpha_attack=0.1, bound=20), FakeSink(), None,
                     audit_rate=0.3, grace=0, rng=random.Random(4))
    truth, results = {}, {"normal": [0, 0], "attack": [0, 0]}
    for i in range(30_000):
        sid, attack = f"s{i}", rng.random() < 0.1
        truth[sid] = attack
        svc.handle(score(sid, rng.expovariate(1.0) + (5.0 if attack else 0.0)), now=i)
        svc.handle(ended(sid), now=i)
        start = len(svc.sink.sent)
        svc.tick(i)
        new = svc.sink.sent[start:]
        if any(t == "review-queue" and v["data"]["audit"] for t, _, v in new):
            svc.handle(label(sid, "attack" if attack else "false_alarm"), now=i)
        decision = next(v for t, _, v in new if t == "flags")["data"]["decision"]
        if i >= 10_000:                                      # after the start-up phase
            key = "attack" if attack else "normal"
            results[key][0] += 1
            results[key][1] += decision != ("flag" if attack else "pass")
    assert results["normal"][1] / results["normal"][0] == pytest.approx(0.05, abs=0.015)
    assert results["attack"][1] / results["attack"][0] == pytest.approx(0.10, abs=0.04)


def test_malformed_messages_are_ignored():
    svc = service()
    for bad in ("x", {"event_type": "anomaly.scored"}, {"event_type": "anomaly.scored", "session_id": "s",
                                                          "data": {"detector": "mock_scorer", "score": "high"}}):
        svc.handle(bad, now=0)
    assert svc.tick(10) == 0


def test_validation():
    with pytest.raises(ValueError):
        service(audit_rate=2)
