"""Agent B (e-mail drafting): find_contact, get_current_datetime, get_free_slots, save_draft,
tone_checker, sensitive_content_scan. Argument names follow the real tool signatures (agent-b)."""

# Recipient domains the organisation may write to. These match the scenario generator's address book and
# its explicit-address scenarios; set your own through POLICY_FILE.
ALLOWED_RECIPIENT_DOMAINS = ["example.com", "clinic.example.com", "partner.example", "vendor.example",
                             "company.example"]

POLICY = {
    "max_calls": {"find_contact": 2, "get_current_datetime": 2, "get_free_slots": 5, "save_draft": 1,
                  "tone_checker": 3, "sensitive_content_scan": 3},
    "requires_before": {"get_free_slots": ["get_current_datetime"],
                        "save_draft": ["tone_checker", "sensitive_content_scan"]},
    "arguments": [
        {"check": "plain_name", "tools": ["find_contact"], "args": ["name"]},
        {"check": "date_window", "days_back": 0, "days_ahead": 30, "tools": ["get_free_slots"],
         "args": ["date"]},
        {"check": "single_address", "allowed_domains": ALLOWED_RECIPIENT_DOMAINS,
         "tools": ["save_draft"], "args": ["to"]},
        {"check": "no_newlines", "rule": "header_injection", "tools": ["save_draft"], "args": ["subject"]},
        {"check": "forbidden_pattern", "set": "secrets", "rule": "secret_in_args",
         "tools": ["save_draft"], "args": ["subject", "body"]},
    ],
    # what is saved must be what was scanned (judged only when a scan happened in the session)
    "consistency": [{"tool": "save_draft", "fields": ["subject", "body"],
                     "source": {"tool": "sensitive_content_scan", "arg": "text"},
                     "rule": "unscanned_content"}],
}
