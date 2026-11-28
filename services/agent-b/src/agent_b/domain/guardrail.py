"""Guardrail for save_draft: plain code checks the draft before it is saved."""

from agent_b.adapters.fake_data import CONTACTS
from agent_b.domain.verification_tools import sensitive_content_scan
import os
# The allow-list: the only addresses a draft may go to (same contacts that seed agent_b_db)
ALLOWED_RECIPIENTS = {c["email"].lower() for c in CONTACTS.values()}
def guardrail_enabled() -> bool:

    """On by default. Turn it off for dataset generation: AGENT_B_GUARDRAIL=off."""
    return os.environ.get("AGENT_B_GUARDRAIL", "on").strip().lower() not in {"off", "0", "false"}

def check_draft(to: str, subject: str, body: str) -> str | None:
    """Return None if the draft may be saved, else the reason it is blocked."""
    if not guardrail_enabled():
        return None
    # 1. Recipient must be a known contact
    if to.strip().lower() not in ALLOWED_RECIPIENTS:
        return f"recipient '{to}' is not one of your contacts"

    # 2. No line breaks in the subject 
    if "\n" in subject or "\r" in subject:
        return "the subject contains a line break"

    # 3. No secrets: run the existing scan ourselves, the model can't skip it
    scan = sensitive_content_scan.invoke({"text": f"Subject: {subject}\n\n{body}"})
    if scan["status"] == "blocked":
        found = ", ".join(sorted({f["type"] for f in scan["findings"] if f["severity"] == "high"}))
        return f"the draft contains sensitive data ({found}); remove it"

    return None  # all checks passed