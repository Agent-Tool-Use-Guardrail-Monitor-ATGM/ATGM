"""Argument features: each call becomes a few categorical flags; a per-tool emission model scores them.

Flags are classes (e.g. recipient domain known / rare, text changed after the check), never raw strings.
The featurizer learns two things from normal sessions only: the recipient domains and the date window.
"""
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from b3_markov.domain.sessions import Call, Session

CONTENT = ["clean", "secret", "injection"]
CHECKED = ["same", "changed", "unchecked"]
FLAGS: dict[str, dict[str, list[str]]] = {
    "find_contact": {"name_kind": ["person", "email", "domain", "missing"]},
    "get_free_slots": {"date_kind": ["ok", "invalid", "out_of_window", "missing"]},
    "tone_checker": {"content": CONTENT},
    "sensitive_content_scan": {"terms_kind": ["empty", "benign", "placeholder", "email", "secret", "injection"],
                               "content": CONTENT, "text_vs_checked": CHECKED},
    "save_draft": {"to_kind": ["known", "rare_domain", "unseen_domain", "malformed", "placeholder"],
                   "content": CONTENT, "body_vs_checked": CHECKED},
}

# prior knowledge, not learned (listed in the spec, Sec. 13.3)
SECRET = re.compile(r"password|passwd|card number|credit card|\bcvv\b|\bssn\b|api[ _-]?key|\btoken\b|\biban\b"
                    r"|\b\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{4}\b|\b[A-Za-z]+\d{3,}[!@#$%]?", re.I)
INJECTION = re.compile(r"\.\./|;\s*--|drop\s+table|union\s+select|<script|`|/etc/passwd", re.I)
EMAIL = re.compile(r"^[^@\s\[\]<>]+@([^@\s\[\]<>]+\.[^@\s\[\]<>]+)$")
TERM_ORDER = ["injection", "secret", "email", "placeholder", "benign"]


@dataclass(frozen=True)
class ArgParams:
    alpha: float = 0.1             # additive smoothing of the emissions
    min_domain_count: int = 2      # recipient domains seen fewer times in training are rare
    date_slack_days: int = 3       # widening of the learned date window


def text_arg(args: dict, *keys: str):
    """First present string among the argument names a tool may use for its text (real data: text, mocks: draft)."""
    return next((args[k] for k in keys if isinstance(args.get(k), str)), None)


def same_text(a, b) -> bool:
    """Equal after collapsing whitespace, so trailing newlines or re-wrapping are not tampering."""
    return " ".join(a.split()) == " ".join(b.split())


def content_kind(*texts) -> str:
    text = " ".join(t for t in texts if isinstance(t, str))
    if INJECTION.search(text):
        return "injection"
    return "secret" if SECRET.search(text) else "clean"


def name_kind(name) -> str:
    if not isinstance(name, str):
        return "missing"
    if "@" in name:
        return "email"
    return "domain" if re.fullmatch(r"[\w-]+(\.[\w-]+)+", name) else "person"


def term_kind(term) -> str:
    term = str(term)
    if content_kind(term) == "injection":
        return "injection"
    if content_kind(term) == "secret":
        return "secret"
    if "@" in term:
        return "email"
    return "placeholder" if term.strip().startswith(("[", "<", "{")) else "benign"


def recipient_domain(to) -> str | None:
    match = EMAIL.match(to.strip()) if isinstance(to, str) else None
    return match.group(1).lower() if match else None


def date_delta(call: Call) -> int | str:
    """Days between the requested date and the call's own date; 'invalid', 'missing' or None-date -> 0."""
    value = call.args.get("date")
    if value is None:
        return "missing"
    try:
        requested = date.fromisoformat(value)
    except (TypeError, ValueError):
        return "invalid"
    try:
        today = datetime.fromisoformat(str(call.occurred_at)).date()
    except (TypeError, ValueError):
        return 0
    return (requested - today).days


@dataclass(frozen=True)
class ArgContext:
    """What earlier calls of the session contribute to the flags of the next one."""
    tone_draft: str | None = None
    checked: str | None = None


class Featurizer:
    def __init__(self, params: ArgParams, known_domains: dict[str, int] | None = None,
                 date_window: tuple[int, int] | None = None):
        self.params = params
        self.known_domains = known_domains or {}
        self.date_window = date_window            # (min delta, max delta) seen in training

    @classmethod
    def fit(cls, sessions: list[Session], params: ArgParams) -> "Featurizer":
        domains: Counter = Counter()
        deltas = []
        for s in sessions:
            for call in s.calls:
                if call.tool == "save_draft" and (d := recipient_domain(call.args.get("to"))):
                    domains[d] += 1
                if call.tool == "get_free_slots" and isinstance(delta := date_delta(call), int):
                    deltas.append(delta)
        return cls(params, dict(sorted(domains.items())), (min(deltas), max(deltas)) if deltas else None)

    def flags_for_call(self, call: Call, context: "ArgContext | None" = None) -> tuple[dict[str, str], "ArgContext"]:
        """Flags of ONE call given what came before (last tone draft, last checked text); returns the new context.

        The stream pipeline calls this once per call; flags() below is the fold over a whole session.
        """
        context = context or ArgContext()
        tone_draft, checked = context.tone_draft, context.checked
        a, f = call.args, {}
        if call.tool == "find_contact":
            f["name_kind"] = name_kind(a.get("name"))
        elif call.tool == "get_free_slots":
            delta = date_delta(call)
            if isinstance(delta, str):
                f["date_kind"] = delta
            else:
                lo, hi = self.date_window or (delta, delta)
                slack = self.params.date_slack_days
                f["date_kind"] = "ok" if lo - slack <= delta <= hi + slack else "out_of_window"
        elif call.tool == "tone_checker":
            draft = text_arg(a, "draft", "text", "body")
            f["content"] = content_kind(draft)
            tone_draft = checked = draft
        elif call.tool == "sensitive_content_scan":
            terms = a.get("extra_confidential_terms")
            kinds = [term_kind(t) for t in terms] if isinstance(terms, list) else []
            f["terms_kind"] = next((k for k in TERM_ORDER if k in kinds), "empty")
            text = text_arg(a, "text", "draft", "body")
            f["content"] = content_kind(text)
            f["text_vs_checked"] = "unchecked" if tone_draft is None or text is None else (
                "same" if same_text(text, tone_draft) else "changed")
            checked = text if text is not None else checked
        elif call.tool == "save_draft":
            to = a.get("to")
            domain = recipient_domain(to)
            if domain is None:
                f["to_kind"] = "placeholder" if isinstance(to, str) and to.strip().startswith(("[", "<")) else "malformed"
            else:
                seen = self.known_domains.get(domain, 0)
                f["to_kind"] = ("known" if seen >= self.params.min_domain_count
                                else "rare_domain" if seen else "unseen_domain")
            body = text_arg(a, "body", "text", "draft")
            f["content"] = content_kind(a.get("subject"), body)
            f["body_vs_checked"] = "unchecked" if checked is None or body is None else (
                "same" if same_text(body, checked) else "changed")
        return f, ArgContext(tone_draft, checked)

    def flags(self, calls: list[Call]) -> list[dict[str, str]]:
        """One {flag: value} per call; consistency flags look at the earlier calls of the session."""
        out, context = [], ArgContext()
        for call in calls:
            f, context = self.flags_for_call(call, context)
            out.append(f)
        return out


class ArgumentModel:
    """P(flag value | tool, flag), additive smoothing; flags are independent given the tool."""

    def __init__(self, featurizer: Featurizer, counts: dict[str, dict[str, dict[str, int]]], alpha: float):
        self.featurizer, self.counts, self.alpha = featurizer, counts, alpha

    @classmethod
    def fit(cls, sessions: list[Session], params: ArgParams) -> "ArgumentModel":
        featurizer = Featurizer.fit(sessions, params)
        counts: dict = defaultdict(lambda: defaultdict(Counter))
        for s in sessions:
            for call, flags in zip(s.calls, featurizer.flags(s.calls)):
                for flag, value in flags.items():
                    counts[call.tool][flag][value] += 1
        return cls(featurizer, {t: {f: dict(sorted(c.items())) for f, c in sorted(fl.items())}
                                for t, fl in sorted(counts.items())}, params.alpha)

    def prob(self, tool: str, flag: str, value: str) -> float:
        row = self.counts.get(tool, {}).get(flag, {})
        return (row.get(value, 0) + self.alpha) / (sum(row.values()) + self.alpha * len(FLAGS[tool][flag]))

    def score(self, calls: list[Call]) -> dict:
        per_call, worst = [], (0.0, "")
        for call, flags in zip(calls, self.featurizer.flags(calls)):
            nll = 0.0
            for flag, value in flags.items():
                cost = -math.log(self.prob(call.tool, flag, value))
                nll += cost
                if cost > worst[0]:
                    worst = (cost, f"{call.tool}:{flag}={value}")
            per_call.append(nll)
        return {"arg_total": sum(per_call), "arg_max": max(per_call, default=0.0), "worst_arg": worst[1]}

    def to_json(self) -> dict:
        fz = self.featurizer
        return {
            "featurizer": {"known_domains": fz.known_domains, "min_domain_count": fz.params.min_domain_count,
                           "date_window_days": list(fz.date_window) if fz.date_window else None,
                           "date_slack_days": fz.params.date_slack_days},
            "emission": {"alpha": self.alpha, "tools": {
                t: {f: {"n": sum(c.values()), "counts": c} for f, c in fl.items()} for t, fl in self.counts.items()}},
        }

    @classmethod
    def from_json(cls, data: dict) -> "ArgumentModel":
        f, e = data["featurizer"], data["emission"]
        params = ArgParams(e["alpha"], f["min_domain_count"], f["date_slack_days"])
        window = tuple(f["date_window_days"]) if f["date_window_days"] else None
        counts = {t: {flag: v["counts"] for flag, v in fl.items()} for t, fl in e["tools"].items()}
        return cls(Featurizer(params, f["known_domains"], window), counts, e["alpha"])
