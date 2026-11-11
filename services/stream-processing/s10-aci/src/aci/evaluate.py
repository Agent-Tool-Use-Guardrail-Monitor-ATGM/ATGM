"""Offline evaluation of conformal triage: decaying vs constant step size.

    python -m aci.evaluate                         # table for both step-size rules
    python -m aci.evaluate --drift --plot aci.png  # scores drift upwards halfway; save a figure

Synthetic sessions: normal score ~ Exp(1), attack score ~ 4 + Exp(1); with --drift every
score rises linearly by 2 over the second half. A random share `audit_rate` of sessions gets
its true label (the simulated reviewer), and only those are learned, as in the service.
"""
from __future__ import annotations

import argparse
import random

from aci.domain.triage import FLAG, PASS, REVIEW, ConformalTriage


def simulate(step: str = "decaying", n: int = 30_000, attack_rate: float = 0.1, audit_rate: float = 0.3,
             drift: bool = False, alpha_normal: float = 0.05, alpha_attack: float = 0.1,
             scale: float | None = None, seed: int = 0) -> dict:
    rng = random.Random(seed)
    tri = ConformalTriage(alpha_normal=alpha_normal, alpha_attack=alpha_attack, bound=20.0, scale=scale, step=step)
    trace = {"pass_up_to": [], "flag_from": [], "decision": [], "attack": []}
    for i in range(n):
        attack = rng.random() < attack_rate
        shift = 2.0 * max(0.0, (i - n / 2) / (n / 2)) if drift else 0.0
        r = shift + rng.expovariate(1.0) + (4.0 if attack else 0.0)
        t = tri.decide("A", r)
        trace["pass_up_to"].append(t.q_compliant)
        trace["flag_from"].append(t.flag_from)
        trace["decision"].append(t.decision)
        trace["attack"].append(attack)
        if rng.random() < audit_rate:
            tri.learn("A", r, attack)
    return trace


def rates(trace: dict, start: int = 0) -> dict:
    normal = [d for d, a in zip(trace["decision"][start:], trace["attack"][start:]) if not a]
    attack = [d for d, a in zip(trace["decision"][start:], trace["attack"][start:]) if a]
    allx = trace["decision"][start:]
    late = trace["pass_up_to"][len(trace["pass_up_to"]) * 3 // 4:]
    return {"normal_not_passed": sum(d != PASS for d in normal) / len(normal),
            "attack_not_flagged": sum(d != FLAG for d in attack) / len(attack),
            "attack_passed": sum(d == PASS for d in attack) / len(attack),
            "review_share": sum(d == REVIEW for d in allx) / len(allx),
            "late_threshold_jitter": max(late) - min(late)}


def plot(traces: dict, path: str, drift: bool) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 4), sharey=True)
    for ax, (step, tr) in zip(axes, traces.items()):
        ax.plot(tr["pass_up_to"], lw=0.8, color="#00798c", label="pass up to (q_compliant)")
        ax.plot(tr["flag_from"], lw=0.8, color="#d1495b", label="flag from (B − q_violating)")
        ax.fill_between(range(len(tr["pass_up_to"])), tr["pass_up_to"], tr["flag_from"],
                        color="#edae49", alpha=0.25, label="review band")
        ax.set_title(f"{step} step size" + ("  (scores drift up in 2nd half)" if drift else ""))
        ax.set_xlabel("session")
        ax.set_ylim(0, 9)
    axes[0].set_ylabel("session score threshold")
    axes[0].legend(loc="upper left", frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n", type=int, default=30_000)
    p.add_argument("--audit-rate", type=float, default=0.3)
    p.add_argument("--drift", action="store_true")
    p.add_argument("--constant-step", type=float, default=0.2, help="step size of the constant (ACI 2021) rule")
    p.add_argument("--plot")
    args = p.parse_args(argv)
    traces = {"decaying": simulate("decaying", args.n, audit_rate=args.audit_rate, drift=args.drift),
              "constant": simulate("constant", args.n, audit_rate=args.audit_rate, drift=args.drift,
                                   scale=args.constant_step)}
    print(f"targets: normal not passed <= 5%, attack not flagged <= 10%   (after the first {args.n // 5} sessions)")
    for step, tr in traces.items():
        r = rates(tr, start=args.n // 5)
        print(f"{step:9s} normal not passed {r['normal_not_passed']:6.2%}   attack not flagged "
              f"{r['attack_not_flagged']:6.2%}   attack passed {r['attack_passed']:6.2%}   "
              f"review share {r['review_share']:6.2%}   threshold jitter (last quarter) {r['late_threshold_jitter']:.3f}")
    if args.plot:
        plot(traces, args.plot, args.drift)
        print(f"plot written to {args.plot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
