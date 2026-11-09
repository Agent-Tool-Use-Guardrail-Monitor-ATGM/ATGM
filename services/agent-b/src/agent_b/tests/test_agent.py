from agent_b.domain.agent import create_agent_b
from agent_b.domain.drafting_tools import *
from agent_b.domain.verification_tools import *

from agent_b.domain.agent import TOOLS

def test_tools_have_expected_names():
    assert find_contact.name == "find_contact"
    assert get_current_datetime.name == "get_current_datetime"
    assert get_free_slots.name == "get_free_slots"
    assert save_draft.name == "save_draft"
    assert tone_checker.name == "tone_checker"
    assert tone_checker.name == "tone_checker"
    assert sensitive_content_scan.name == "sensitive_content_scan"

def test_agent_has_required_tools():
    names = {tool.name for tool in TOOLS}
    assert {
        "find_contact",
        "get_current_datetime",
        "get_free_slots",
        "save_draft",
        "sensitive_content_scan",
        "tone_checker",
    } <= names

def test_agent_is_created():
    assert create_agent_b("qwen3:1.7b") is not None

def test_agent_calls_permitted_tools_on_normal_request():
    """Live test: needs a running Ollama model."""
    agent = create_agent_b("qwen3:1.7b")
    result = agent.invoke({"messages": [{
        "role": "user",
        "content": "Write a formal email to my professor about the course schedule.",
    }]})
    names = set()
    for message in result["messages"]:
        for call in getattr(message, "tool_calls", None) or []:
            names.add(call["name"])

    for tool_name in names:
        assert {tool_name} <= {
        "find_contact",
        "get_current_datetime",
        "get_free_slots",
        "save_draft",
        "sensitive_content_scan",
        "tone_checker",
    }