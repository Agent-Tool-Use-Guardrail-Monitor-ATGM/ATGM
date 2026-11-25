import json

from sklearn.dummy import DummyClassifier

from b2_classifier.adapters.model_store import save, load, latest


def test_save_load_and_find_latest_model(tmp_path):
    model = DummyClassifier(strategy="constant", constant="unsafe_args")
    model.fit([[0], [1]], ["unsafe_args", "unsafe_args"])

    metrics = {"model": "random_forest", "accuracy": 0.9}

    folder = save(model, metrics, tmp_path)

    assert (folder / "model.joblib").exists()
    assert (folder / "metrics.json").exists()

    loaded = load(folder)
    assert loaded.predict([[0], [1]]).tolist() == [
        "unsafe_args",
        "unsafe_args",
    ]

    saved_metrics = json.loads(
        (folder / "metrics.json").read_text(encoding="utf-8")
    )
    assert saved_metrics["accuracy"] == 0.9

    assert latest(tmp_path) == folder
    assert latest(tmp_path, "random_forest") == folder
    assert latest(tmp_path, "logistic_regression") is None
