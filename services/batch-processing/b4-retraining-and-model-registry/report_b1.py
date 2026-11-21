"""Export promoted B1 model metrics as CSV."""

import argparse
import csv
import json
import sys
from pathlib import Path


def report(models_dir, output):
    fields = ("version", "champion_version", "champion_macro_f1",
              "challenger_macro_f1", "held_out_sessions")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for path in sorted((models_dir / "b1-binary").glob("*/metrics.json")):
        metrics = json.loads(path.read_text(encoding="utf-8"))
        if metrics.get("eligible_for_promotion") is True:
            writer.writerow({field: metrics[field] for field in fields})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, default=Path("models"))
    args = parser.parse_args()
    report(args.models_dir, sys.stdout)


if __name__ == "__main__":
    main()
