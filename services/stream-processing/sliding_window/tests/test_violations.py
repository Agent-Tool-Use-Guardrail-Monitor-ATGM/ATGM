from sliding_window.domain.violations import ToolCallMemory, ViolationReader


def tool_call(event_id, tool, partition=0, memory=None):
    memory = memory or ToolCallMemory()
    memory.remember("tool-calls.B", partition, {
        "event_id": event_id, "event_type": "tool_call.completed",
        "data": {"agent_id": "B", "tool_name": tool}})
    return memory


def alarm(call_id, detector="online_forest", agent="B"):
    return {"event_id": f"alarm-{call_id}-{detector}", "event_type": "alarm.raised",
            "data": {"scored_event_id": call_id, "agent_id": agent, "detector": detector}}


def test_alarm_becomes_violation_on_its_tool():
    memory = tool_call("call1", "save_draft", partition=2)
    violation = ViolationReader(memory).from_alarm(0, alarm("call1"))
    assert (violation.agent, violation.partition, violation.item) == ("B", 2, "anomaly:save_draft")


def test_call_is_counted_once_even_with_two_detectors():
    reader = ViolationReader(tool_call("call1", "save_draft"))
    assert reader.from_alarm(0, alarm("call1", "online_forest")) is not None
    assert reader.from_alarm(0, alarm("call1", "mock_scorer")) is None


def test_session_alarm_and_unknown_call():
    memory = ToolCallMemory()
    memory.remember("tool-calls.A", 1, {"event_id": "end1", "event_type": "session.ended", "data": {}})
    reader = ViolationReader(memory)
    assert reader.from_alarm(0, alarm("end1", agent="A")).item == "anomaly:<session>"
    assert reader.from_alarm(0, alarm("missing")).item == "anomaly:unknown"


def test_memory_keeps_only_the_latest_calls():
    memory = ToolCallMemory(limit=2)
    for number in range(3):
        tool_call(f"call{number}", "save_draft", memory=memory)
    assert memory.find("call0") is None and memory.find("call2") is not None


def test_flags_only_with_configured_type():
    reader = ViolationReader(tool_call("call1", "save_draft"), flag_types=["violation.flagged"])
    flag = {"event_id": "flag1", "event_type": "violation.flagged",
            "data": {"tool_call_event_id": "call1", "violation_type": "out_of_order"}}
    assert reader.from_flag(0, flag).item == "out_of_order:save_draft"
    other = {"event_id": "decision1", "event_type": "decision.made", "data": {}}
    assert reader.from_flag(0, other) is None