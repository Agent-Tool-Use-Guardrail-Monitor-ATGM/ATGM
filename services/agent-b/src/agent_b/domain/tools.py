from langchain.tools import tool


@tool
def email_draft(    
    subject: str,
    body: str,
    recipient: str = "[Recipient]",
    tone: str = "formal",
) -> dict:
    """Create an email draft. Nothing is sent.
    
    Call this AFTER you have written the email yourself. You are responsible
    for composing the body from the user's instructions; do not ask the user for them.

    Args:
        subject: A concise subject line for the email.
        body: The complete email text you write in the requested tone, including 
            greeting and sign-off.
        recipient: Who the email is for. A role or relationship is
            acceptable (e.g. "my manager", "landlord", "HR"). If no
            email address or name is given, use the role as stated.
            Never ask the user for a name or address.
        tone: The tone used in the draft (e.g. formal, friendly, apologetic).
    """
    recipient = recipient.strip()
    subject = subject.strip()
    body = body.strip()

    if not recipient:
        return {"status": "error", "message": "Recipient is required."}
    if not subject:
        return {"status": "error", "message": "Subject is required."}
    if not body:
        return {"status": "error", "message": "Body is required."}

    return {
        "status": "draft_created",
        "sent": False,
        "to": recipient,
        "subject": subject,
        "body": body,
        "tone": tone,
    }