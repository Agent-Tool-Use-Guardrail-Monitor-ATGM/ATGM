"""Quality and safety tools for Email Emilio.
 
Both tools are deterministic (regex / rule based): no extra LLM call, so they
are fast, free, repeatable, and work well even with small local models.
"""

import re
from typing import Any, Dict, List, Optional

from langchain.tools import tool

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
 
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
 
 
def _words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9'’]+", text)
 
 
def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(_words(p)) > 0]
 
 
def _mask(value: str) -> str:
    """Show just enough of a value to identify it, never the whole secret."""
    value = value.strip()
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "*" * min(len(value) - 4, 8) + value[-2:]
 
 
# ---------------------------------------------------------------------------
# Tone / style checker
# ---------------------------------------------------------------------------
 
_TONE_ALIASES = {
    "formal": "formal",
    "professional": "professional",
    "business": "professional",
    "neutral": "professional",
    "warm": "warm",
    "friendly": "warm",
    "polite": "warm",
    "kind": "warm",
    "firm": "firm",
    "assertive": "firm",
    "direct": "firm",
    "casual": "casual",
    "informal": "casual",
}
 
_CONTRACTION_RE = re.compile(
    r"\b(?:\w+n['’]t|\w+['’](?:re|ve|ll|d|m)|it['’]s|that['’]s|let['’]s|"
    r"there['’]s|here['’]s|what['’]s)\b",
    re.IGNORECASE,
)
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_GREETING_RE = re.compile(
    r"^\s*(dear|hi|hello|hey|good (?:morning|afternoon|evening)|greetings)\b",
    re.IGNORECASE,
)
_SIGN_OFF_RE = re.compile(
    r"\b(sincerely|best regards|kind regards|warm regards|regards|best wishes|"
    r"best|thanks|thank you|many thanks|cheers|yours (?:sincerely|faithfully)|"
    r"respectfully|take care)\b",
    re.IGNORECASE,
)
 
_SLANG = {
    "hey", "yo", "gonna", "wanna", "gotta", "btw", "lol", "thx", "pls", "cuz",
    "kinda", "sorta", "dude", "yeah", "nope", "ya", "omg",
}
_HEDGES = [
    "maybe", "perhaps", "i think", "i guess", "just", "sorry", "if possible",
    "if you don't mind", "kind of", "sort of", "hopefully", "would it be possible",
]
_DIRECTIVES = [
    "must", "need", "required", "require", "expect", "no later than", "deadline",
    "immediately", "please ensure", "by monday", "by tuesday", "by wednesday",
    "by thursday", "by friday", "by end of", "by [", "will need",
]
_WARM_MARKERS = [
    "thank", "appreciate", "grateful", "glad", "pleased", "happy", "hope",
    "look forward", "wonderful", "great to", "kind", "welcome",
]
_HOSTILE = [
    "per my last email", "as i already", "as i said", "obviously", "clearly you",
    "your fault", "ridiculous", "stupid", "idiot", "useless", "incompetent",
    "whatever",
]
_CLICHES = [
    "i hope this email finds you well", "i trust this email finds you well",
    "delve", "i wanted to reach out", "touch base", "circle back",
]
_FORMAL_GREETINGS = ("dear", "good morning", "good afternoon", "good evening", "greetings")
_FORMAL_SIGN_OFFS = (
    "sincerely", "kind regards", "best regards", "respectfully", "yours", "regards",
)
 
 
def _split_subject(draft: str) -> tuple:
    """Separate an optional 'Subject: ...' first line from the body."""
    lines = draft.strip().splitlines()
    if lines and lines[0].lower().startswith("subject:"):
        return lines[0].split(":", 1)[1].strip(), "\n".join(lines[1:]).strip()
    return "", draft.strip()
 
 
def _count_phrases(text_lower: str, phrases: List[str]) -> List[str]:
    found = []
    for p in phrases:
        if re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", text_lower):
            found.append(p)
    return found
 
 
@tool
def tone_checker(
    draft: str,
    requested_tone: str = "professional",
    style_profile: Optional[Dict[str, Any]] = None,
) -> dict:
    """Check an email draft against a requested tone and, optionally, the user's style profile.
 
    Call this after writing a draft and before showing it to the user.
 
    Args:
        draft: The full draft. May start with a 'Subject: ...' line followed by the body.
        requested_tone: One of 'formal', 'professional', 'warm', 'firm', 'casual'.
            Synonyms such as 'friendly' or 'assertive' are accepted. Defaults to 'professional'.
        style_profile: Optional dict describing how the user usually writes. Supported keys:
            greeting (str, e.g. 'Hi'), sign_off (str, e.g. 'Best'), uses_contractions (bool),
            avg_words_per_sentence (number), max_words (int), avoid_phrases (list of str).
 
    Returns:
        A dict with 'matches_tone' (bool), 'score' (0-100), 'issues' (each with severity,
        code, message and suggestion), plus 'metrics' about the draft.
    """
    if not isinstance(draft, str) or not draft.strip():
        return {
            "matches_tone": False,
            "score": 0,
            "issues": [{
                "severity": "major",
                "code": "empty_draft",
                "message": "The draft is empty.",
                "suggestion": "Write the email first, then check it.",
            }],
            "metrics": {},
        }
 
    notes: List[str] = []
    tone = _TONE_ALIASES.get((requested_tone or "").strip().lower())
    if tone is None:
        notes.append(
            f"Unknown tone '{requested_tone}'; checked against 'professional' instead."
        )
        tone = "professional"
 
    subject, body = _split_subject(draft)
    lowered = body.lower()
    words = _words(body)
    sentences = _sentences(body)
    word_count = len(words)
    avg_len = round(word_count / len(sentences), 1) if sentences else 0.0
 
    non_empty = [ln.strip() for ln in body.splitlines() if ln.strip()]
    first_line = non_empty[0] if non_empty else ""
    tail = "\n".join(non_empty[-3:])
 
    greeting_match = _GREETING_RE.match(first_line)
    greeting = greeting_match.group(1).lower() if greeting_match else None
    sign_off_match = _SIGN_OFF_RE.search(tail)
    sign_off = sign_off_match.group(1).lower() if sign_off_match else None
 
    contractions = _CONTRACTION_RE.findall(body)
    exclamations = body.count("!")
    emojis = _EMOJI_RE.findall(body)
    slang = sorted({w.lower() for w in words if w.lower() in _SLANG})
    shouting = [
        w for w in re.findall(r"\b[A-Z]{4,}\b", body)
        if w not in {"ASAP", "FYI", "NDA", "CEO", "CFO", "CTO", "HTML", "HTTP", "HTTPS"}
    ]
 
    issues: List[Dict[str, str]] = []
    penalty = 0
 
    def add(severity: str, code: str, message: str, suggestion: str) -> None:
        nonlocal penalty
        penalty += 20 if severity == "major" else 8
        issues.append({
            "severity": severity,
            "code": code,
            "message": message,
            "suggestion": suggestion,
        })
 
    # ---- Checks that apply to every tone ---------------------------------
    hostile = _count_phrases(lowered, _HOSTILE)
    if hostile:
        add("major", "hostile_language",
            f"Language that may read as hostile or passive-aggressive: {', '.join(hostile)}.",
            "Rephrase neutrally and focus on the request or the facts.")
 
    if shouting:
        add("minor", "all_caps",
            f"All-caps words can read as shouting: {', '.join(shouting[:3])}.",
            "Use normal capitalization.")
 
    cliches = _count_phrases(lowered, _CLICHES)
    if cliches:
        add("minor", "cliche",
            f"Stock phrases make the email feel generic: {', '.join(cliches)}.",
            "Replace with a direct opening that states the purpose.")
 
    if not greeting:
        add("minor", "missing_greeting", "The email has no greeting.",
            "Start with a greeting such as 'Hello [Recipient],'.")
    if not sign_off:
        add("minor", "missing_sign_off", "The email has no sign-off.",
            "End with a closing such as 'Best regards,' and the sender's name.")
 
    # ---- Tone-specific checks --------------------------------------------
    if tone in {"formal", "professional"}:
        if slang:
            add("major", "slang", f"Slang or informal words: {', '.join(slang)}.",
                "Replace with standard business wording.")
        if emojis:
            add("major", "emoji", "Emoji are out of place in this tone.", "Remove the emoji.")
        if exclamations > 1:
            add("minor", "exclamations",
                f"{exclamations} exclamation marks; this tone calls for restraint.",
                "Use at most one, or none.")
 
    if tone == "formal":
        if contractions:
            add("major", "contractions",
                f"Contractions in a formal email: {', '.join(sorted({c.lower() for c in contractions})[:4])}.",
                "Write them out (e.g. 'do not', 'I am').")
        if greeting and greeting not in _FORMAL_GREETINGS:
            add("minor", "informal_greeting", f"'{greeting.title()}' is informal.",
                "Use 'Dear [Recipient],' or 'Good morning,'.")
        if sign_off and not sign_off.startswith(_FORMAL_SIGN_OFFS):
            add("minor", "informal_sign_off", f"'{sign_off.title()}' is informal.",
                "Use 'Sincerely,' or 'Kind regards,'.")
 
    if tone == "warm":
        if not _count_phrases(lowered, _WARM_MARKERS):
            add("major", "not_warm",
                "No friendly or appreciative wording found.",
                "Add a thank-you, a kind remark or a positive closing line.")
        if exclamations > 3:
            add("minor", "exclamations", f"{exclamations} exclamation marks is a lot.",
                "Keep to two or three at most.")
        if emojis:
            add("minor", "emoji", "Emoji may be too much unless you know the recipient well.",
                "Consider removing them.")
 
    if tone == "firm":
        hedges = _count_phrases(lowered, _HEDGES)
        if len(hedges) >= 2:
            add("major", "hedging",
                f"Hedging weakens the message: {', '.join(hedges)}.",
                "State the request directly and remove softeners.")
        if not _count_phrases(lowered, _DIRECTIVES):
            add("major", "no_clear_demand",
                "No clear requirement or deadline was found.",
                "State exactly what is expected and by when.")
        if exclamations > 0:
            add("minor", "exclamations", "Exclamation marks undermine a firm tone.",
                "Use full stops instead.")
        if emojis or slang:
            add("minor", "informal_markers", "Slang or emoji weaken a firm tone.",
                "Remove them.")
 
    if tone == "casual":
        if re.search(r"\b(pursuant|henceforth|aforementioned|herewith)\b", lowered):
            add("minor", "stiff_wording", "Legalistic wording feels stiff for a casual email.",
                "Use everyday words.")
        if greeting == "dear":
            add("minor", "stiff_greeting", "'Dear' is stiff for a casual email.", "Use 'Hi [Recipient],'.")
 
    # ---- User style profile ----------------------------------------------
    profile_checked = False
    if isinstance(style_profile, dict) and style_profile:
        profile_checked = True
 
        want_greeting = style_profile.get("greeting")
        if want_greeting and not first_line.lower().startswith(str(want_greeting).lower()):
            add("minor", "style_greeting",
                f"You usually open with '{want_greeting}'.",
                f"Start with '{want_greeting} [Recipient],'.")
 
        want_sign_off = style_profile.get("sign_off")
        if want_sign_off and str(want_sign_off).lower() not in tail.lower():
            add("minor", "style_sign_off",
                f"You usually sign off with '{want_sign_off}'.",
                f"End with '{want_sign_off},'.")
 
        uses_contractions = style_profile.get("uses_contractions")
        if uses_contractions is False and contractions:
            add("minor", "style_contractions", "You usually avoid contractions.",
                "Write them out.")
        if uses_contractions is True and tone != "formal" and word_count > 40 and not contractions:
            add("minor", "style_contractions", "You usually use contractions; this reads stiff.",
                "Use natural contractions where they fit.")
 
        target_len = style_profile.get("avg_words_per_sentence")
        if isinstance(target_len, (int, float)) and target_len > 0 and avg_len:
            if abs(avg_len - target_len) / target_len > 0.5:
                add("minor", "style_sentence_length",
                    f"Average sentence length is {avg_len} words; yours is usually about {target_len}.",
                    "Shorten or combine sentences to match your usual rhythm.")
 
        max_words = style_profile.get("max_words")
        if isinstance(max_words, int) and word_count > max_words:
            add("minor", "style_length",
                f"The email has {word_count} words; you usually stay under {max_words}.",
                "Trim it.")
 
        avoid = style_profile.get("avoid_phrases")
        if isinstance(avoid, list):
            hit = [p for p in avoid if isinstance(p, str) and p.lower() in lowered]
            if hit:
                add("minor", "style_avoid_phrases",
                    f"Contains phrases you avoid: {', '.join(hit)}.", "Reword them.")
 
    # ---- General readability (soft) --------------------------------------
    if avg_len > 28:
        add("minor", "long_sentences", f"Sentences average {avg_len} words.",
            "Break long sentences up.")
    if word_count > 250:
        add("minor", "long_email", f"The email is {word_count} words long.",
            "Tighten it; put the main ask near the top.")
 
    score = max(0, 100 - penalty)
    has_major = any(i["severity"] == "major" for i in issues)
 
    return {
        "requested_tone": tone,
        "matches_tone": score >= 70 and not has_major,
        "score": score,
        "issues": issues,
        "notes": notes,
        "style_profile_checked": profile_checked,
        "metrics": {
            "word_count": word_count,
            "sentence_count": len(sentences),
            "avg_words_per_sentence": avg_len,
            "exclamation_marks": exclamations,
            "contractions": len(contractions),
            "greeting": greeting,
            "sign_off": sign_off,
            "subject_present": bool(subject),
        },
    }
 
 
# ---------------------------------------------------------------------------
# Sensitive content scan
# ---------------------------------------------------------------------------
 
_TOKEN_PATTERNS = [
    ("private_key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("aws_access_key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("github_token", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    ("slack_token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    ("api_key", r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    ("google_api_key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("jwt", r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ("connection_string", r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s@]+@\S+"),
]
 
_CREDENTIAL_RE = re.compile(
    r"\b(password|passwd|pwd|passcode|pin|secret|api[_ -]?key|access[_ -]?key|token)\b"
    r"(\s*[:=]\s*|\s+is\s+)['\"]?([^\s'\",;]{4,})",
    re.IGNORECASE,
)
_CARD_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
_SSN_RE = re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
_PHONE_RES = [
    re.compile(r"(?<![\w+])\+\d[\d\s().-]{7,}\d"),
    re.compile(r"\(\d{2,4}\)[\s.-]?\d[\d\s.-]{5,}\d"),
    re.compile(r"\b\d{3}[-.\s]\d{3,4}[-.\s]\d{4}\b"),
]
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
 
_CONFIDENTIAL_TERMS = [
    "strictly confidential", "confidential", "internal use only", "internal only",
    "do not distribute", "do not forward", "not for distribution", "trade secret",
    "proprietary", "nda", "non-disclosure", "attorney-client", "privileged",
    "embargoed", "under embargo", "unreleased", "restricted",
]
 
 
def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0
 
 
def _iban_ok(candidate: str) -> bool:
    iban = candidate.replace(" ", "")
    if not 15 <= len(iban) <= 34:
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1
 
 
def _is_placeholder(value: str) -> bool:
    v = value.strip()
    return (
        v[:1] in "[<{(" or
        bool(re.fullmatch(r"[xX*#._-]+", v)) or
        v.lower() in {"password", "secret", "token", "yourpassword", "changeme"}
    )
 
 
@tool
def sensitive_content_scan(
    text: str,
    extra_confidential_terms: Optional[List[str]] = None,
) -> dict:
    """Scan an email draft for credentials, personal data and confidential wording.
 
    Call this on the final subject and body before showing the draft to the user.
 
    Detects: API keys and tokens, private keys, passwords/PINs, connection strings,
    credit card numbers (Luhn-validated), IBANs (checksum-validated), US SSNs,
    phone numbers, email addresses, and confidentiality markers such as
    'confidential' or 'do not forward'.
 
    Args:
        text: The full draft (subject and body).
        extra_confidential_terms: Optional extra words or phrases to treat as confidential,
            such as project code names.
 
    Returns:
        A dict with 'status' ('blocked', 'review' or 'clear'), 'safe_to_send' (bool),
        'findings' (type, severity, masked preview, recommendation), and 'redacted_text'
        where secrets and sensitive identifiers are replaced by placeholders.
        Findings never contain the full secret value.
    """
    if not isinstance(text, str) or not text.strip():
        return {"status": "clear", "safe_to_send": True, "summary": "Nothing to scan.",
                "findings": [], "redacted_text": text or ""}
 
    # Each candidate: (start, end, type, severity, redact?, recommendation)
    candidates: List[tuple] = []
 
    for name, pattern in _TOKEN_PATTERNS:
        for m in re.finditer(pattern, text):
            candidates.append((m.start(), m.end(), name, "high", True,
                               "Remove it. Never put credentials in an email; share them through a password manager."))
 
    for m in _CREDENTIAL_RE.finditer(text):
        label, sep = m.group(1), m.group(2)
        value = m.group(3).rstrip(".,;:")  # drop sentence punctuation
        if len(value) < 4 or _is_placeholder(value):
            continue
        if sep.strip().lower() == "is" and not re.search(r"[\d\W]", value):
            continue  # "the token is expired" style prose
        candidates.append((m.start(3), m.start(3) + len(value), f"credential ({label.lower()})", "high", True,
                           "Replace with a placeholder and send credentials through a secure channel."))
 
    for m in _CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            candidates.append((m.start(), m.end(), "credit_card_number", "high", True,
                               "Remove the card number."))
 
    for m in _IBAN_RE.finditer(text):
        if _iban_ok(m.group()):
            candidates.append((m.start(), m.end(), "iban", "medium", True,
                               "Only include bank details if the recipient needs them; prefer a secure channel."))
 
    for m in _SSN_RE.finditer(text):
        candidates.append((m.start(), m.end(), "us_ssn", "high", True,
                           "Remove the social security number."))
 
    for pattern in _PHONE_RES:
        for m in pattern.finditer(text):
            digits = re.sub(r"\D", "", m.group())
            if 9 <= len(digits) <= 15:
                candidates.append((m.start(), m.end(), "phone_number", "low", False,
                                   "Confirm the recipient should receive this number."))
 
    for m in _EMAIL_RE.finditer(text):
        candidates.append((m.start(), m.end(), "email_address", "low", False,
                           "Confirm the address is correct and meant to be shared."))
 
    terms = list(_CONFIDENTIAL_TERMS)
    if extra_confidential_terms:
        terms += [t.strip() for t in extra_confidential_terms if isinstance(t, str) and t.strip()]
    terms.sort(key=len, reverse=True)  # longest first so "strictly confidential" wins
    for term in terms:
        for m in re.finditer(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE):
            candidates.append((m.start(), m.end(), "confidential_term", "medium", False,
                               "Check that the recipient is allowed to see this content and that the wording is intended."))
 
    # Resolve overlaps: higher severity first, then longer match, then earliest.
    candidates.sort(key=lambda c: (-_SEVERITY_RANK[c[3]], -(c[1] - c[0]), c[0]))
    accepted: List[tuple] = []
    for cand in candidates:
        if all(cand[1] <= a[0] or cand[0] >= a[1] for a in accepted):
            accepted.append(cand)
    accepted.sort(key=lambda c: c[0])
 
    findings = []
    for start, end, ftype, severity, _redact, advice in accepted:
        raw = text[start:end]
        preview = raw if ftype == "confidential_term" else _mask(raw)
        findings.append({
            "type": ftype,
            "severity": severity,
            "preview": preview,
            "position": start,
            "recommendation": advice,
        })
 
    redacted = text
    for start, end, ftype, _sev, redact, _adv in sorted(accepted, key=lambda c: c[0], reverse=True):
        if redact:
            label = re.sub(r"\W+", "_", ftype).strip("_").upper()
            redacted = redacted[:start] + f"[REDACTED_{label}]" + redacted[end:]
 
    top = max((_SEVERITY_RANK[f["severity"]] for f in findings), default=0)
    status = "blocked" if top == 3 else "review" if top == 2 else "clear"
 
    counts: Dict[str, int] = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
 
    if status == "blocked":
        summary = "Secrets or sensitive identifiers found. Do not present this draft until they are removed."
    elif status == "review":
        summary = "Possibly confidential content found. Ask the user to confirm before sending."
    elif findings:
        summary = "Only low-risk contact details found (normal for an email)."
    else:
        summary = "No sensitive content detected."
 
    return {
        "status": status,
        "safe_to_send": status == "clear",
        "summary": summary,
        "counts": counts,
        "findings": findings,
        "redacted_text": redacted,
    }