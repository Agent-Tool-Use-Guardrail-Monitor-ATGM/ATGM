from agent_b.domain.agent import create_agent_b
from agent_b.domain.tools import sensitive_content_scan, tone_checker

def test_tools_have_expected_names():
    assert tone_checker.name == "tone_checker"
    assert sensitive_content_scan.name == "sensitive_content_scan"


def test_agent_is_created():
    assert create_agent_b() is not None


def test_agent_runs_both_checks_on_normal_request():
    """Live test: needs a running Ollama model."""
    agent = create_agent_b()
    result = agent.invoke({"messages": [{
        "role": "user",
        "content": "Write a formal email to my professor about the course schedule.",
    }]})
    names = set()
    for message in result["messages"]:
        for call in getattr(message, "tool_calls", None) or []:
            names.add(call["name"])
    assert {"tone_checker", "sensitive_content_scan"} <= names