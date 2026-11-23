import json
import sys

import pytest

from b3_markov import main as cli
from test_dataset import rec, write

TOOLS = ["inspect_dataset", "aggregate_statistics", "finalize_statistics"]


def agent_a_records():
    records = []
    for i in range(24):
        sid = f"n{i}"
        records.append(rec(sid, 1, "session.started", {}, label="model_failure" if i < 3 else "tool_trace_allowed"))
        for j, tool in enumerate(TOOLS[: 1 + i % 3]):
            records.append(rec(sid, 2 + 2 * j, "tool_call.requested", {"tool_call_id": f"{sid}{j}", "name": tool},
                               label="model_failure" if i < 3 else "tool_trace_allowed"))
            records.append(rec(sid, 3 + 2 * j, "tool_call.completed", {"tool_call_id": f"{sid}{j}"},
                               label="model_failure" if i < 3 else "tool_trace_allowed"))
    for i in range(6):
        sid = f"p{i}"
        records.append(rec(sid, 1, "session.started", {}, "prompt_injected", "direct_prompt_injection", "answer_violation"))
        records.append(rec(sid, 2, "tool_call.requested", {"tool_call_id": f"{sid}0", "name": "describe_columns"},
                           "prompt_injected", "direct_prompt_injection", "answer_violation"))
        records.append(rec(sid, 3, "tool_call.completed", {"tool_call_id": f"{sid}0"},
                           "prompt_injected", "direct_prompt_injection", "answer_violation"))
    return records


def run(monkeypatch, tmp_path, *argv):
    monkeypatch.setattr(sys, "argv", ["main", "--models-dir", str(tmp_path / "models"), "--bootstrap", "20", *argv])
    cli.main()
    (folder,) = (tmp_path / "models" / "b3-markov-chain" / argv[argv.index("--agent") + 1]).glob("*")
    return folder


def test_agent_a_run_is_sequence_only_with_agent_defaults_and_agent_folder(monkeypatch, tmp_path):
    path = write(tmp_path, agent_a_records())
    folder = run(monkeypatch, tmp_path, "--agent", "A", "--dataset-file", str(path), "--exclude-labels", "model_failure",
                 "--save-fold-models", "--folds", "5")
    table = json.loads((folder / "transition_table.json").read_text())
    metrics = json.loads((folder / "metrics.json").read_text())
    assert "arguments" not in table and table["training"]["agent"] == "A"
    assert table["training"]["vocabulary_source"] == "declared" and "describe_columns" in table["vocabulary"]
    assert table["calibration"]["percentile"] == 95.0 and table["calibration"]["call_threshold"]["1"] < 0
    assert metrics["parameters"]["no_arguments"] is True and metrics["alpha"]["mode"] == "cv"
    assert metrics["sensitivity_without_labels"]["n_removed"] == 3
    assert metrics["data"]["n_normal"] == 24 and len(list((folder / "folds").glob("fold_*.json"))) == 5


def test_agent_a_needs_its_dataset_file(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["main", "--agent", "A", "--models-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        cli.main()
