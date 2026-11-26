"""Scores a session with a Markov model: negative log-likelihood per transition (natural log)."""
import math
from dataclasses import dataclass

from b3_markov.domain.sequences import END, START, UNK, context_key, max_run_length, transitions

MAX_CALLS = 10      # spec: a session never has more than 10 tool calls


@dataclass
class Params:
    smoothing: str = "additive"        # additive | floor | backoff
    alpha: float = 0.1
    epsilon: float = 1e-5
    backoff_weight: float = 0.4


class MarkovModel:
    """Multi-order Markov chain stored as counts: counts[order][context_key][next] = n."""

    def __init__(self, vocabulary: list[str], counts: dict[int, dict[str, dict[str, int]]], params: Params):
        self.vocabulary = sorted(vocabulary)
        self._vocab_set = set(self.vocabulary)
        self.counts = counts
        self.params = params
        self.orders = sorted(counts)
        self._totals = {order: {key: sum(row.values()) for key, row in rows.items()}
                        for order, rows in counts.items()}
        self._n_next = len(self.vocabulary) + 2        # tools + END + UNK

    def _p(self, order: int, context: tuple[str, ...], nxt: str) -> tuple[float, int, int]:
        """(smoothed probability, training count of this transition, row total of the context)."""
        key = context_key(context)
        row = self.counts[order].get(key)
        count = row.get(nxt, 0) if row else 0
        total = self._totals[order].get(key, 0)
        p = self.params
        if p.smoothing == "floor":
            return (count / total if count else p.epsilon), count, total
        if p.smoothing == "backoff":
            if count:
                return count / total, count, total
            if order == 0:
                return p.alpha / (p.alpha * self._n_next + total), count, total
            return p.backoff_weight * self._p(order - 1, context[1:], nxt)[0], count, total
        # additive: unseen context -> uniform over next symbols
        if not row:
            return 1.0 / self._n_next, count, total
        return (count + p.alpha) / (total + p.alpha * self._n_next), count, total

    def known(self, token: str) -> bool:
        return token in self._vocab_set or token in (START, END, UNK)

    def prob(self, order: int, context: tuple[str, ...], nxt: str) -> tuple[float, bool]:
        """Returns (probability, seen) where seen = this exact transition occurred in training."""
        p, count, _ = self._p(order, context, nxt)
        return p, count > 0

    def score(self, order: int, tools: list[str]) -> dict:
        """Whole-session score as a fold of step() over the T+1 padded transitions."""
        steps = transitions(tools, order, self._vocab_set)
        stepped = [step(self, order, ctx, nxt) for ctx, nxt in steps]
        lps = [lp for lp, _, _ in stepped]
        nlls = [-lp for lp in lps]
        unseen = sum(1 for _, count, _ in stepped if count == 0)
        worst = max(range(len(steps)), key=lambda i: nlls[i])
        ctx, nxt = steps[worst]
        return {
            "mean_nll": sum(nlls) / len(nlls),
            "total_nll": sum(nlls),
            "n_unseen": unseen,
            "n_transitions": len(steps),
            "unseen_fraction": unseen / len(steps),
            "min_log_p": min(lps),                      # m(s) of spec Sec. 14.3
            "min_p": math.exp(min(lps)),
            "log_probs": lps,                           # one per transition; the last one is the <END> step
            "worst_transition": f"{context_key(ctx)} -> {nxt}",
            "n_calls": len(tools),
            "exceeds_max_len": len(tools) > MAX_CALLS,
            "max_run_length": max_run_length(tools),
        }


def step(model: MarkovModel, order: int, context: tuple[str, ...], symbol: str) -> tuple[float, int, int]:
    """One transition: (ln p(symbol | context), training count of the transition, row total of the context).

    Batch and stream both score through this function. Tokens outside the model's vocabulary count as <UNK>.
    """
    context = tuple(t if model.known(t) else UNK for t in context)
    symbol = symbol if model.known(symbol) else UNK
    p, count, total = model._p(order, context, symbol)
    return math.log(p), count, total


SCORE_MODES = ("joint", "joint_max", "seq", "args")


class Detector:
    """The Markov chain over tool names, optionally with the argument-class emission model (spec Sec. 13)."""

    def __init__(self, chain: MarkovModel, arguments=None, mode: str = "joint"):
        self.chain, self.arguments, self.mode = chain, arguments, mode

    @property
    def orders(self) -> list[int]:
        return self.chain.orders

    def score(self, order: int, session) -> dict:
        """`session` is a Session, a list of Call, or (sequence only) a list of tool names."""
        calls = getattr(session, "calls", session)
        tools = [c if isinstance(c, str) else c.tool for c in calls]
        result = self.chain.score(order, tools)
        result["seq_score"] = result["mean_nll"]
        if self.arguments is None or any(isinstance(c, str) for c in calls):
            result["score"] = result["mean_nll"]
            return result
        result.update(self.arguments.score(calls))
        result["joint"] = (result["total_nll"] + result["arg_total"]) / result["n_transitions"]
        result["joint_max"] = result["mean_nll"] + result["arg_max"]
        result["args"] = result["arg_max"]
        result["seq"] = result["mean_nll"]
        result["score"] = result[self.mode]
        return result
