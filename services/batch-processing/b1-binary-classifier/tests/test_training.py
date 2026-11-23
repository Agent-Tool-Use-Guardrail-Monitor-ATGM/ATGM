import json

from b1_classifier.adapters import dataset, model_store
from b1_classifier.domain.training import train_and_evaluate


def fake_sessions(n_compliant=20, n_violating=60):
    compliant = [{"n_calls": 4, "scanned_before_save": 1, "secret_like_argument": 0}] * n_compliant
    violating = [{"n_calls": 6, "scanned_before_save": 0, "secret_like_argument": 1}] * n_violating
    return compliant + violating, ["compliant"] * n_compliant + ["violating"] * n_violating


def test_learns_a_clear_signal():
    features, labels = fake_sessions()
    for kind in ("random_forest", "logistic_regression"):
        result = train_and_evaluate(features, labels, kind=kind)
        assert result.metrics["macro_f1"] == 1.0
        assert result.model.predict([{"n_calls": 4, "scanned_before_save": 1}])[0] == "compliant"


def test_save_writes_model_and_metrics(tmp_path):
    features, labels = fake_sessions()
    result = train_and_evaluate(features, labels)
    folder = model_store.save(result.model, result.metrics, tmp_path)
    assert folder.name.endswith("_random_forest")
    assert (folder / "model.joblib").is_file()
    assert json.loads((folder / "metrics.json").read_text())["n_sessions"] == 80

def test_latest_picks_newest_of_kind(tmp_path):

    base = tmp_path / model_store.MODEL_NAME
    for name in ["2026-01-01T00-00-00_random_forest", "2026-02-01T00-00-00_random_forest",
                 "2026-03-01T00-00-00_logistic_regression"]:
        (base / name).mkdir(parents=True)
        (base / name / "model.joblib").write_bytes(b"x")

    assert model_store.latest(tmp_path).name.endswith("logistic_regression")
    assert model_store.latest(tmp_path, kind="random_forest").name.startswith("2026-02")
    assert model_store.latest(tmp_path / "empty") is None

def test_loads_the_dataset_files(tmp_path):
    (tmp_path / "events").mkdir()
    (tmp_path / "labels").mkdir()
    events = [
        {"event_type": "session.started", "session_id": "s1", "data": {"category": "normal"}},
        {"event_type": "tool_call.completed", "session_id": "s1",
         "data": {"tool_name": "save_draft", "session_call_index": 2}},
        {"event_type": "tool_call.completed", "session_id": "s1",
         "data": {"tool_name": "find_contact", "session_call_index": 1}},
    ]
    (tmp_path / "events" / "events_for_x.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    (tmp_path / "labels" / "labels_for_x.jsonl").write_text(json.dumps({"scenario_id": "s1", "label": "adversarial"}))
    [(session, calls, label)] = dataset.from_dataset(tmp_path, "x.jsonl")
    assert session == "s1" and label == "violating"
    assert [c["tool_name"] for c in calls] == ["find_contact", "save_draft"]