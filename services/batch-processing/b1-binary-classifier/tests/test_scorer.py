from b1_classifier.adapters import model_store
from b1_classifier.domain.features import session_features
from b1_classifier.domain.training import make_model
from b1_classifier.scorer import Scorer

GOOD = [{"tool_name": "find_contact", "arguments": {"name": "Anna"}, "session_call_index": 1},
        {"tool_name": "save_draft", "arguments": {"body": "Hi"}, "session_call_index": 2}]
BAD = [{"tool_name": "delete_everything", "arguments": {"password": "1234"}, "session_call_index": 1}]


def save_model(models_dir):
    features = [session_features(GOOD)] * 5 + [session_features(BAD)] * 5
    labels = ["compliant"] * 5 + ["violating"] * 5
    model = make_model("random_forest").fit(features, labels)
    return model_store.save(model, {"model": "random_forest"}, models_dir)


def session_events(session, calls):
    yield {"event_type": "session.started", "session_id": session, "event_id": "s", "data": {"agent_id": "B"}}
    for call in calls:
        yield {"event_type": "tool_call.completed", "session_id": session, "event_id": "c",
               "data": {"agent_id": "B", **call}}
    yield {"event_type": "session.ended", "session_id": session, "event_id": f"end-{session}",
           "data": {"agent_id": "B"}}


def run(scorer, session, calls):
    results = [scorer.handle(event) for event in session_events(session, calls)]
    assert results[:-1] == [None] * (len(results) - 1)       # only session.ended gives a score
    return results[-1]


def test_scores_violating_session_higher(tmp_path):
    save_model(tmp_path)
    scorer = Scorer(tmp_path)

    good = run(scorer, "good", GOOD)
    bad = run(scorer, "bad", BAD)

    assert good["data"]["detector"] == "b1_classifier"
    assert bad["data"]["scored_event_id"] == "end-bad"
    assert bad["data"]["score"] > 0.5 > good["data"]["score"]


def test_no_model_no_score(tmp_path):
    scorer = Scorer(tmp_path)
    assert run(scorer, "s1", GOOD) is None


def test_model_update_reloads(tmp_path):
    scorer = Scorer(tmp_path)
    folder = save_model(tmp_path)
    scorer.on_model_update({"data": {"model": "b1-binary", "version": folder.name}})
    assert scorer.version == folder.name