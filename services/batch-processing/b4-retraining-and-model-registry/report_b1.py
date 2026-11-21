"""Export promoted B1 model metrics as CSV and optionally plot them."""

import argparse
import csv
import json
import sys
from pathlib import Path


FIELDS = ("version", "champion_version", "champion_macro_f1",
          "challenger_macro_f1", "held_out_sessions")


def promotions(models_dir):
    for path in sorted((models_dir / "b1-binary").glob("*/metrics.json")):
        metrics = json.loads(path.read_text(encoding="utf-8"))
        if metrics.get("eligible_for_promotion") is True:
            yield {field: metrics[field] for field in FIELDS}


def plot(rows, destination):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(8, max(2.5, 0.4 * len(rows) + 1.5)), layout="constrained")
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    rounds = range(1, len(rows) + 1)
    champion = [row["champion_macro_f1"] for row in rows]
    challenger = [row["challenger_macro_f1"] for row in rows]
    axis.hlines(rounds, champion, challenger, color="0.65")
    axis.scatter(champion, rounds, label="Champion", marker="o")
    axis.scatter(challenger, rounds, label="Challenger", marker="D")
    axis.set(xlim=(0, 1), xlabel="Macro F1 on each round's holdout", ylabel="Promotion round")
    axis.set_yticks(list(rounds))
    axis.invert_yaxis()
    axis.legend()
    figure.savefig(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, default=Path("models"))
    parser.add_argument("--plot", type=Path, help="Optional chart path, such as promotions.png")
    args = parser.parse_args()
    rows = list(promotions(args.models_dir))
    if args.plot:
        if not rows:
            parser.error("No saved B4 promotions to plot")
        plot(rows, args.plot)
    writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)


if __name__ == "__main__":
    main()
