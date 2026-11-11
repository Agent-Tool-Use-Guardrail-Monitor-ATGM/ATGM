"""Offline evaluation: run SPOT or DSPOT on a recorded score stream, report and plot.

    python -m dspot.evaluate                       # synthetic demo stream
    python -m dspot.evaluate --csv scores.csv --column score --labels label --review

The first `--init` scores calibrate the detector (they should be normal); the rest
are classified. With labels (1 = attack, 0 = normal) it reports precision, recall and
the false-alarm rate on normal scores. `--review` simulates the review queue: every
alarm on a normal score is confirmed as a false alarm and learned.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass

import numpy as np

from dspot.domain.dspot import DSPOT
from dspot.domain.spot import SPOT, Decision


@dataclass(frozen=True)
class Report:
    decisions: list[Decision]
    alarm_rate: float
    precision: float | None = None       # None without labels (or without alarms)
    recall: float | None = None
    false_alarm_rate: float | None = None

    def summary(self) -> str:
        lines = [f"scores classified: {len(self.decisions)}", f"alarm rate:        {self.alarm_rate:.4%}"]
        for name in ("precision", "recall", "false_alarm_rate"):
            value = getattr(self, name)
            if value is not None:
                lines.append(f"{name + ':':<19}{value:.4%}")
        return "\n".join(lines)


def make_detector(method: str, q: float, level: float, depth: int) -> SPOT | DSPOT:
    if method == "spot":
        return SPOT(q=q, level=level)
    if method == "dspot":
        return DSPOT(q=q, level=level, depth=depth)
    raise ValueError(f"unknown method {method!r}")


def evaluate(detector, scores, labels=None, init: int = 3_000, review: bool = False) -> Report:
    """Calibrate on scores[:init], classify the rest, compare with labels if given."""
    scores = np.asarray(scores, dtype=float)
    if review and labels is None:
        raise ValueError("review needs labels: the simulated reviewer must know the truth")
    detector.initialize(scores[:init])
    stream = scores[init:]
    truth = None if labels is None else np.asarray(labels, dtype=bool)[init:]

    decisions = []
    for i, x in enumerate(stream):
        d = detector.update(x)
        if review and d.alarm and not truth[i]:
            detector.confirm_normal(x)
        decisions.append(d)

    alarms = np.array([d.alarm for d in decisions])
    if truth is None:
        return Report(decisions, float(alarms.mean()))
    hits = np.sum(alarms & truth)
    return Report(
        decisions,
        alarm_rate=float(alarms.mean()),
        precision=float(hits / alarms.sum()) if alarms.any() else None,
        recall=float(hits / truth.sum()) if truth.any() else None,
        false_alarm_rate=float(alarms[~truth].mean()) if (~truth).any() else None,
    )


def synthetic_stream(seed: int = 0, n: int = 20_000, init: int = 3_000, n_attacks: int = 30):
    """Normal scores whose level drifts upwards, with injected attacks after `init`."""
    rng = np.random.default_rng(seed)
    scores = np.linspace(0.0, 6.0, n) + rng.normal(size=n)
    labels = np.zeros(n, dtype=int)
    attacks = rng.choice(np.arange(init, n), size=n_attacks, replace=False)
    scores[attacks] += rng.uniform(6.0, 10.0, size=n_attacks)
    labels[attacks] = 1
    return scores, labels


def read_csv(path: str, column: str, label_column: str | None):
    scores, labels = [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            scores.append(float(row[column]))
            if label_column:
                labels.append(int(row[label_column]))
    return np.array(scores), (np.array(labels) if label_column else None)


def plot(report: Report, path: str, labels=None, init: int = 0, title: str = "") -> None:
    """Scores, alarm threshold and alarms (plus true attacks if labelled) as a PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    d = report.decisions
    idx = np.arange(init, init + len(d))
    score = np.array([x.score for x in d])
    alarm = np.array([x.alarm for x in d])
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(idx, score, lw=0.4, color="#8c96a0", label="score")
    ax.plot(idx, [x.threshold for x in d], lw=1.2, color="#d1495b", label="alarm threshold")
    ax.scatter(idx[alarm], score[alarm], s=22, color="#d1495b", zorder=3, label="alarm")
    if labels is not None:
        attack = np.asarray(labels, dtype=bool)[init:]
        ax.scatter(idx[attack], score[attack], s=60, facecolors="none", edgecolors="#00798c",
                   zorder=4, label="true attack")
    ax.set_xlabel("event index")
    ax.set_ylabel("anomaly score")
    ax.set_title(title)
    ax.legend(loc="upper left", frameon=False, ncol=4)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", help="score file; without it a synthetic demo stream is used")
    p.add_argument("--column", default="score")
    p.add_argument("--labels", help="label column (1 = attack, 0 = normal)")
    p.add_argument("--method", choices=["spot", "dspot"], default="dspot")
    p.add_argument("--q", type=float, default=1e-3)
    p.add_argument("--level", type=float, default=0.98)
    p.add_argument("--depth", type=int, default=20)
    p.add_argument("--init", type=int, default=3_000)
    p.add_argument("--review", action="store_true", help="simulate reviewers confirming false alarms")
    p.add_argument("--plot", help="write a PNG plot to this path")
    args = p.parse_args(argv)

    if args.csv:
        scores, labels = read_csv(args.csv, args.column, args.labels)
    else:
        scores, labels = synthetic_stream(init=args.init)
    detector = make_detector(args.method, args.q, args.level, args.depth)
    report = evaluate(detector, scores, labels, init=args.init, review=args.review)
    print(report.summary())
    if args.plot:
        title = f"{args.method.upper()}  q={args.q:g}" + ("  with review" if args.review else "")
        plot(report, args.plot, labels, init=args.init, title=title)
        print(f"plot written to {args.plot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
