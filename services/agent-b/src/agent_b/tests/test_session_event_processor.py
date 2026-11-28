"""What the event reporter publishes for each tool call."""
from agent_b.adapters.session_event_processor import SessionEventPublisher
from agent_b.domain.drafting_tools import find_contact, get_free_slots
from agent_b.domain.verification_tools import sensitive_content_scan, tone_checker


class ListSink:
    def __init__(self):
        self.events = []

    def send(self, key, event):
        self.events.append(event)

    def flush(self):
        pass


def run(tool, args):
    """Run one tool call the way the agent does and return the published tool event."""
    sink = ListSink()
    publisher = SessionEventPublisher(sink, run_id="r1", session_id="s1")
    publisher.start()
    tool.invoke({"type": "tool_call", "id": "c1", "name": tool.name, "args": args},
                config={"callbacks": [publisher]})
    publisher.end()
    [event] = [e for e in sink.events if e["event_type"].startswith("tool_call.")]
    return event


def test_error_answers_count_as_failed_calls():
    assert run(find_contact, {"name": "Bob"})["event_type"] == "tool_call.failed"
    assert run(get_free_slots, {"date": "next Friday"})["event_type"] == "tool_call.failed"


def test_normal_answers_count_as_completed_calls():
    assert run(find_contact, {"name": "Anna"})["event_type"] == "tool_call.completed"
    assert run(get_free_slots, {"date": "2026-11-28"})["event_type"] == "tool_call.completed"  # a weekend is still an answer


def test_the_scan_decision_is_published_without_the_secret():
    event = run(sensitive_content_scan, {"text": "My card number is 4111 1111 1111 1111."})
    assert event["data"]["result"] == {"status": "blocked", "finding_types": ["credit_card_number"]}
    assert "4111" not in str(event["data"]["result"])


def test_the_tone_decision_is_published():
    event = run(tone_checker, {"draft": "Dear Anna,\nThank you for your help.\nKind regards,\nAron",
                               "requested_tone": "formal"})
    assert set(event["data"]["result"]) == {"matches_tone", "score"}


def test_tools_without_a_decision_have_no_result_field():
    assert "result" not in run(find_contact, {"name": "Anna"})["data"]
