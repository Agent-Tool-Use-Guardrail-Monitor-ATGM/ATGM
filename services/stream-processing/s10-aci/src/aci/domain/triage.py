"""Conformal triage: pass / flag / review for each session, with error rates you choose.

A session's suspicion r (e.g. the highest anomaly score in the session, clipped to [0, B]) is
turned into a prediction set over {compliant, violating}, one decaying-step tracker per label
(class-conditional, "Mondrian" conformal) and per agent:

    compliant in set  <=>  r       <= q_c     (tracker on s_c = r,     fed with normal sessions)
    violating in set  <=>  B - r   <= q_v     (tracker on s_v = B - r, fed with attack sessions)

    {compliant}             -> pass
    {violating}             -> flag
    {compliant, violating}  -> review    (could be either)
    {}                      -> review    (fits neither well)

Long-run guarantees, over the labelled sessions the trackers learn from:
    normal sessions that are not passed (flagged or reviewed)  ->  at most alpha_normal
    attack sessions that are not flagged (passed or reviewed)  ->  at most alpha_attack
So attacks slip through silently at most alpha_attack of the time, normal sessions are blocked
at most alpha_normal of the time, and the uncertain middle goes to human review.

Both thresholds start at 0, so at the start every session is reviewed (a safe start);
the trackers then narrow the review band as labels arrive.
"""
from __future__ import annotations

from dataclasses import dataclass

from aci.domain.tracker import QuantileTracker

PASS, FLAG, REVIEW = "pass", "flag", "review"


@dataclass(frozen=True)
class Triage:
    decision: str
    prediction_set: tuple[str, ...]
    q_compliant: float              # pass if r <= q_compliant ...
    flag_from: float                # ... flag if r >= flag_from (= B - q_violating)


class ConformalTriage:
    def __init__(self, alpha_normal: float = 0.05, alpha_attack: float = 0.1, bound: float = 20.0,
                 scale: float | None = None, eps: float = 0.1, step: str = "decaying") -> None:
        self.alpha_normal, self.alpha_attack, self.bound = alpha_normal, alpha_attack, bound
        self._kw = {"bound": bound, "scale": scale, "eps": eps, "step": step}
        QuantileTracker(alpha_normal, **self._kw)            # validate parameters early
        QuantileTracker(alpha_attack, **self._kw)
        self.trackers: dict[str, tuple[QuantileTracker, QuantileTracker]] = {}

    def _pair(self, agent: str) -> tuple[QuantileTracker, QuantileTracker]:
        if agent not in self.trackers:
            self.trackers[agent] = (QuantileTracker(self.alpha_normal, **self._kw),
                                    QuantileTracker(self.alpha_attack, **self._kw))
        return self.trackers[agent]

    def _clip(self, r: float) -> float:
        return min(max(float(r), 0.0), self.bound)

    def decide(self, agent: str, r: float) -> Triage:
        compliant, violating = self._pair(agent)
        r = self._clip(r)
        labels = tuple(name for name, inside in (("compliant", compliant.covers(r)),
                                                 ("violating", violating.covers(self.bound - r))) if inside)
        decision = {("compliant",): PASS, ("violating",): FLAG}.get(labels, REVIEW)
        return Triage(decision, labels, compliant.q, self.bound - violating.q)

    def learn(self, agent: str, r: float, violating: bool) -> bool:
        """Feed a labelled session; returns True if its label was outside the prediction set."""
        compliant_t, violating_t = self._pair(agent)
        r = self._clip(r)
        return violating_t.update(self.bound - r) if violating else compliant_t.update(r)

    def status(self) -> dict[str, dict]:
        out = {}
        for agent, (c, v) in self.trackers.items():
            out[agent] = {"pass_up_to": round(c.q, 4), "flag_from": round(self.bound - v.q, 4),
                          "normal_labels": c.t, "normal_not_passed": c.miscoverage,
                          "attack_labels": v.t, "attack_not_flagged": v.miscoverage}
        return out
