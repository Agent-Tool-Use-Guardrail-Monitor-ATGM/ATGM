from agent_b.adapters.llm_client import create_llm
from agent_b.domain.agent import create_agent_b, tone_checker, sensitive_content_scan


def test_create_agent_b_returns_agent():
    """Agent B should initialize successfully."""
    agent = create_agent_b()

    assert agent is not None


def test_agent_registers_email_draft_tool():
    """Agent B should register the email_draft tool."""
    agent = create_agent_b()

    assert agent is not None
    assert tone_checker.name == "tone_checker"
    assert sensitive_content_scan.name == "sensitive_content_scan"


def test_agent_handles_normal_email_request():
    """Agent B should use the email_draft tool for a normal request."""
    agent = create_agent_b()

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Draft a formal email to professor@example.com. "
                        "Explain that I am sick and cannot attend class today. "
                        "Use the email_draft tool. Do not send anything."
                    ),
                }
            ]
        }
    )

    messages = result["messages"]
    tool_calls = [
        call
        for message in messages
        for call in getattr(message, "tool_calls", [])
    ]

    assert any(
        call["name"] == "tone_checker"
        for call in tool_calls
    )
    
    assert any(
        call["name"] == "sensitive_content_scan"
        for call in tool_calls
    )
