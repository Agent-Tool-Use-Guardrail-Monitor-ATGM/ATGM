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
    reader = ViolationReader(tool_call("call1", "save_draft", partition=2))
    violation = reader.read(0, alarm("call1"))
    assert (violation.agent, violation.partition, violation.item) == ("B", 2, "anomaly:save_draft")


def test_call_is_counted_once_even_with_two_detectors():
    reader = ViolationReader(tool_call("call1", "save_draft"))
    assert reader.read(0, alarm("call1", "online_forest")) is not None
    assert reader.read(0, alarm("call1", "mock_scorer")) is None


def test_alarms_on_our_own_scores_are_ignored():
    reader = ViolationReader(tool_call("call1", "save_draft"))
    assert reader.read(0, alarm("call1", "topk_counts")) is None


def test_rule_violation_and_aci_flag():
    reader = ViolationReader(tool_call("call1", "send_email"))
    rule = {"event_id": "v1", "event_type": "violation.flagged",
            "data": {"flagged_event_id": "call1", "agent_id": "B", "rule": "allow_list", "severity": "high"}}
    assert reader.read(0, rule).item == "allow_list:send_email"
    flag = {"event_id": "d1", "event_type": "decision.made", "data": {"agent_id": "A", "decision": "flag"}}
    passed = {"event_id": "d2", "event_type": "decision.made", "data": {"agent_id": "A", "decision": "pass"}}
    assert reader.read(0, flag).item == "aci:flag"
    assert reader.read(0, passed) is None


def test_unknown_call_and_bounded_memory():
    memory = ToolCallMemory(limit=2)
    for number in range(3):
        tool_call(f"call{number}", "save_draft", memory=memory)
    assert memory.find("call0") is None and memory.find("call2") is not None
    assert ViolationReader(memory).read(0, alarm("missing")).item == "anomaly:unknown"
