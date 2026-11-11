from sliding_window.domain.violations import ToolCallMemory, ViolationReader
from sliding_window.service import Settings, TopKService


def new_service():
    settings = Settings(k=2, nodes=3, slot_seconds=1, units=10, epsilon=0, stats_every=5)
    return TopKService(settings, ViolationReader(ToolCallMemory()))


def call_with_alarm(service, number, tool, now):
    call_id = f"{tool}-{number}"
    service.handle("tool-calls.B", number % 3, {
        "event_id": call_id, "event_type": "tool_call.completed",
        "data": {"agent_id": "B", "tool_name": tool}}, now)
    return service.handle("alerts", 0, {
        "event_id": f"alarm-{call_id}", "event_type": "alarm.raised",
        "data": {"scored_event_id": call_id, "agent_id": "B"}}, now)


def test_new_violation_spike_is_published():
    service = new_service()
    for number in range(60):
        call_with_alarm(service, number, "find_contact" if number % 2 else "save_draft", number * 0.1)
    published = []
    for number in range(60, 100):
        published += call_with_alarm(service, number, "get_free_slots", number * 0.1)
    changes = [event for _, _, event in published if event["event_type"] == "topk.changed"]
    assert any("anomaly:get_free_slots" in event["data"]["entered"] for event in changes)


def test_stats_are_sent_and_old_violations_expire():
    service = new_service()
    for number in range(30):
        call_with_alarm(service, number, "save_draft", number * 0.1)
    stats = [event for _, _, event in service.tick(3.0) if event["event_type"] == "topk.stats"]
    assert stats[0]["data"]["top"][0]["item"] == "anomaly:save_draft"
    service.tick(100.0)
    assert service.monitors["B"].total("anomaly:save_draft") == 0


def test_other_flag_events_are_ignored():
    service = new_service()
    assert service.handle("flags", 0, {"event_id": "x", "event_type": "decision.made", "data": {}}, 1.0) == []
    assert service.monitors == {}