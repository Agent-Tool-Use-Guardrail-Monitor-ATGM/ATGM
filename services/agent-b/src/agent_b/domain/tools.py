from langchain.tools import tool

@tool
def email_draft(
    recipient: str,
    purpose: str,
    tone: str = "formal",
    key_points: list[str] | None = None,
) -> dict:
    """Create an email draft"""
    #TODO
    raise NotImplementedError(
        "todo"
    )