from sliding_window.domain.violations import ToolCallMemory, ViolationReader
from sliding_window.service import Settings, TopKService


def new_service():
    settings = Settings(k=2, nodes=3, slot_seconds=1, units=10, epsilon=0)
    return TopKService(settings, ViolationReader(ToolCallMemory()))


def call_with_alarm(service, number, tool, now):
    call_id = f"{tool}-{number}"
    service.handle("tool-calls.B", number % 3, {
        "event_id": call_id, "event_type": "tool_call.completed",
        "data": {"agent_id": "B", "tool_name": tool}}, now)
    return service.handle("alerts", 0, {
        "event_id": f"alarm-{call_id}", "event_type": "alarm.raised", "session_id": "s1",
        "data": {"scored_event_id": call_id, "agent_id": "B", "detector": "online_forest"}}, now)


def test_every_violation_gets_its_window_count_as_score():
    service = new_service()
    outputs = [call_with_alarm(service, number, "save_draft", number * 0.1) for number in range(5)]
    topic, key, score = outputs[-1][0]
    assert (topic, key, score["event_type"]) == ("scores", "B", "anomaly.scored")
    assert score["data"]["detector"] == "topk_counts" and score["data"]["score"] == 5.0
    assert score["data"]["scored_event_id"] == "alarm-save_draft-4" and score["session_id"] == "s1"


def test_summary_per_slot_shows_top_k_and_new_entries():
    service = new_service()
    service.tick(0.0)
    for number in range(30):
        call_with_alarm(service, number, "find_contact" if number % 2 else "save_draft", number * 0.01)
    for number in range(30, 60):
        call_with_alarm(service, number, "get_free_slots", 0.5)
    summaries = [event for topic, _, event in service.tick(1.0) if topic == "stats"]
    data = summaries[0]["data"]
    assert summaries[0]["event_type"] == "counts.summary"
    assert data["top"][0] == {"item": "anomaly:get_free_slots", "count": 30}
    assert "anomaly:get_free_slots" in data["entered"]
    assert service.tick(1.5) == []                   # same slot: no second summary


def test_old_violations_expire():
    service = new_service()
    call_with_alarm(service, 1, "save_draft", 0.0)
    service.tick(100.0)
    assert service.monitors["B"].total("anomaly:save_draft") == 0
