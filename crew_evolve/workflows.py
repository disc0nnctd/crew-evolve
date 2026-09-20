"""Small, reviewable workflow reuse for crew questions.

This module deliberately handles only approved workflow examples.  It does not
call a model, execute an operation, or infer a new business rule.  A caller can
ask :func:`guard_request` first and then use :func:`route` only when the guard
returns ``None``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from itertools import islice


__all__ = ("route", "guard_request", "candidates", "workflow_candidates", "provenance", "workflow_key")


_ACTIONS = frozenset(("coverage", "roster", "summary"))
_PLACEHOLDERS = frozenset(("{duty}", "{role}"))
MAX_WORKFLOW_SCAN = 128
MAX_ROUTE_CANDIDATES = 16

# These are intentionally short, explicit vocabularies.  They are a bounded
# bridge between approved examples, rather than a general language model.
_COVERAGE_PATTERNS = (
    r"\bcover(?:age|ing)?\b",
    r"\beligib(?:le|ility)\b",
    r"\bcandidat(?:e|es)\b",
    r"\bqualified\b",
    r"\bshortlist\b",
    r"\bstep\s+in\b",
    r"\bwho\s+can\b",
    r"\bfind\s+(?:an?\s+)?(?:eligible\s+)?(?:person|someone|crew)\b",
    r"\b(?:suggest|show)\s+(?:possible\s+)?(?:people|persons|someone|crew|available)\b",
    r"\bwhich\s+[^.!?;]+\s+could\b",
)
_ROSTER_PATTERNS = (
    r"\broster\b",
    r"\bschedul(?:e|ed|ing)\b",
    r"\bduty[- ]by[- ]duty\b",
    r"\bplanned\s+(?:duty\s+)?(?:slot|position)s?\b",
    r"\blist\s+(?:the\s+)?(?:duty\s+)?(?:slot|position)s?\b",
    r"\b(?:show|display|inspect|pull\s+up)\s+(?:the\s+)?(?:duty\s+)?(?:slot|position|assignment)s?\b",
)
_SUMMARY_PATTERNS = (
    r"\bsummary\b",
    r"\bsummar(?:ize|ise|y)\b",
    r"\boverview\b",
    r"\baggregate\b",
    r"\bheadcount\b",
    r"\bhow\s+many\b",
    r"\bcount\b",
    r"\bcounts?\b",
    r"\btotal(?:s|\s+up)?\b",
    r"\brecord\s+count\b",
)
_SUMMARY_STRONG_PATTERNS = _SUMMARY_PATTERNS
_WRITE_PATTERNS = (
    r"\bassign(?:s|ed|ment)?\b",
    r"\b(?:unassign|release)\b",
    r"\b(?:delete|remove|change|update|set|add|edit|modify)\b",
    r"\bschedule\s+(?:a\s+)?(?:person|crew|someone)\b",
    r"\bminimum\s+rest\b",
    r"\bhome\s+base\b",
    r"\bpolicy\b",
)
_INJECTION_PATTERNS = (
    r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\b",
    r"\b(?:system|developer)\s+message\b",
    r"\b(?:system|developer)\s+instructions?\b",
    r"\bprompt\s+injection\b",
    r"\bjailbreak\b",
    r"\bexecute\s+(?:this|the|a)\b",
    r"\bcall\s+(?:the\s+)?(?:tool|network)\b",
)

# Coverage currently checks the recorded roster, qualifications, availability,
# duty length, rest, overlap, location, and rolling duty hours.  Keep the
# unsupported qualifiers explicit so an approved coverage example cannot make
# a broader request look answered.
_UNSUPPORTED_CONSTRAINTS = (
    ("cost", (
        r"\bcheapest\b",
        r"\blowest[- ]cost\b",
        r"\bleast[- ]cost\b",
        r"\bcost(?:s|ing)?\b",
    )),
    ("certificate validity", (
        r"\b(?:valid|invalid|expired?|unexpired|expiry|expiration|expires?|renew(?:al|ed)?)\s+(?:medical\s+)?(?:certificate|certification|licen[cs]e)s?\b",
        r"\b(?:medical\s+)?(?:certificate|certification|licen[cs]e)s?\s+(?:is\s+)?(?:valid|invalid|expired?|unexpired|due|expires?|expiry|expiration)\b",
        r"\bmedical\s+(?:certificate|certification)\b",
    )),
    ("reserve callout windows", (
        r"\breserve[- ](?:callout|call[- ]out|on[- ]call|window)\b",
        r"\bon[- ]call\s+(?:window|availability)\b",
        r"\bcall[- ]out\s+(?:window|availability)\b",
    )),
    ("calendar-day or flight-hour limits", (
        r"\bcalendar[- ]days?\b",
        r"\bflight[- ]hours?\b",
        r"\bblock[- ]hours?\b",
    )),
    ("delay scenarios", (
        r"\b(?:after|following)\s+(?:a\s+)?(?:[a-z0-9]+\s+){0,4}delay(?:ed|s|ing)?\b",
        r"\b(?:if|when)\b[^.!?;]{0,80}\bdelay(?:ed|s|ing)?\b",
    )),
    ("positioning or sector rules", (
        r"\bpositioning\b",
        r"\bdeadhead(?:ing)?\b",
        r"\bsectors?\b",
    )),
    ("named-person filters", (
        r"\b(?:exclud(?:e|ing|ed)|omit(?:ting)?|leav(?:e|ing)(?:\s+out)?|except(?:\s+for)?|but\s+not)\s+(?:the\s+)?(?:crew\s+member\s+|person\s+)?[a-z][a-z'-]*(?:\s+[a-z][a-z'-]*)?\b",
        r"\bwithout\s+(?!violat(?:e|ing)|break(?:ing)?|consider(?:ing)?|minimum|required|rest\b)(?:considering\s+)?(?:the\s+)?(?:crew\s+member\s+|person\s+)?[a-z][a-z'-]*(?:\s+[a-z][a-z'-]*)?\b",
    )),
    ("hypothetical changes", (
        r"\b(?:if|when|assuming|suppose|supposing|what\s+if)\b[^.!?;]{0,80}\b(?:sick|ill|unavailable|absent|injured|calls?\s+in\s+sick|unfit)\b",
    )),
)

_UNSUPPORTED_REPLIES = {
    "cost": "I can check basic coverage from recorded availability, qualifications, and rest, but I cannot compare cost. Ask for a basic current coverage check.",
    "certificate validity": "I can check recorded qualifications, but I cannot verify certificate validity or expiry. Ask for a basic current coverage check.",
    "reserve callout windows": "I can check recorded availability, qualifications, and rest, but I cannot apply reserve callout windows. Correct existing availability data first or ask for a basic current coverage check.",
    "calendar-day or flight-hour limits": "I can check recorded duty and rest information, but I cannot apply calendar-day or flight-hour limits. Ask for a basic current coverage check.",
    "delay scenarios": "I can check current recorded coverage, but I cannot model a delay scenario. Ask for a basic current coverage check.",
    "positioning or sector rules": "I can check basic current coverage, but I cannot apply positioning or sector rules. Ask for a basic current coverage check.",
    "named-person filters": "I can check current coverage, but I cannot exclude named people. Ask for a basic current coverage check.",
    "hypothetical changes": "I can check the current workspace, but I cannot evaluate hypothetical changes such as illness. Ask for a basic current coverage check.",
}


def _words(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.casefold())


def _normalise_inputs(duty_ids: Iterable[str] | Mapping[str, object], roles: Iterable[str]) -> tuple[list[str], list[str]]:
    duties = list(duty_ids.keys()) if isinstance(duty_ids, Mapping) else list(duty_ids or ())
    roles = list(roles or ())
    duties = [x for x in duties if isinstance(x, str) and x.strip()]
    roles = [x for x in roles if isinstance(x, str) and x.strip()]
    # Duplicate labels make a result ambiguous, so retain one stable spelling.
    duties = list(dict.fromkeys(duties))
    roles = list(dict.fromkeys(roles))
    return duties, roles


def _boundary_pattern(value: str) -> str:
    return r"(?<![\w])" + re.escape(value.casefold()) + r"(?![\w])"


def _role_pattern(role: str) -> str:
    # A canonical first_officer role is accepted in the question as either
    # ``first_officer`` or ``first officer`` (and a hyphenated spelling).
    bits = [re.escape(bit) for bit in re.split(r"[_ -]+", role.casefold()) if bit]
    if not bits:
        return r"(?!)"
    return r"(?<![\w])" + r"(?:[_ -]+)".join(bits) + r"(?![\w])"


def _extract_duties(question: str, duty_ids: list[str]) -> list[str]:
    # Tokenise once and validate exact membership.  This keeps route latency
    # bounded when a workspace has many duties, and avoids D-1 matching D-10.
    by_exact = {duty: duty for duty in duty_ids}
    found: list[tuple[int, int, str]] = []
    for match in re.finditer(r"(?<![\w])[^\s,.;!?(){}\[\]\\\"'/:]+(?![\w])", question):
        token = match.group(0).rstrip("'’")
        if token.casefold().endswith("'s"):
            token = token[:-2]
        # Identifiers are operator supplied values, so case is significant.
        # This avoids silently choosing whichever of D-100 and d-100 happened
        # to be inserted last into a casefolded dictionary.
        duty = by_exact.get(token)
        if duty is not None:
            found.append((match.start(), match.start() + len(token), duty))
    return list(dict.fromkeys(duty for _, _, duty in sorted(found)))


def _extract_roles(question: str, roles: list[str]) -> list[str]:
    # Index role spellings by their first token, then scan the question once.
    # The old one-regex-per-role approach made a large roster unnecessarily
    # expensive and could make overlapping role names order dependent.
    text = question.casefold()
    tokens = [(match.start(), match.end(), match.group(0))
              for match in re.finditer(r"[a-z0-9]+", text)]
    index: dict[str, list[tuple[tuple[str, ...], str]]] = {}
    for role in roles:
        parts = tuple(part for part in re.split(r"[_ -]+", role.casefold()) if part)
        if parts:
            index.setdefault(parts[0], []).append((parts, role))
    found: list[tuple[int, int, str]] = []
    for position, (start, _, token) in enumerate(tokens):
        for parts, role in index.get(token, ()):
            end_position = position + len(parts)
            if end_position > len(tokens):
                continue
            selected = tokens[position:end_position]
            if tuple(item[2] for item in selected) != parts:
                continue
            if any(not re.fullmatch(r"[\s_-]+", text[b:a])
                   for (_, b, _), (a, _, _) in zip(selected, selected[1:])):
                continue
            found.append((start, selected[-1][1], role))
    # Prefer the longest spelling at a collision and retain question order.
    found.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2].casefold(), item[2]))
    selected: list[tuple[int, int, str]] = []
    for item in found:
        if any(item[0] < end and start < item[1] for start, end, _ in selected):
            continue
        selected.append(item)
    return list(dict.fromkeys(role for _, _, role in selected))


def workflow_key(question: str, duty_ids: Iterable[str] | Mapping[str, object], roles: Iterable[str]) -> tuple[str, list[str], list[str]]:
    """Return the compatible canonical template key and extracted targets.

    Only tokens that exactly match supplied duties and roles are substituted.
    This has the same shape as ``learning.workflow_key`` while accepting
    spaced and underscored role spellings without scanning every duty with a
    separate expression.
    """

    duties, role_values = _normalise_inputs(duty_ids, roles)
    original = question.strip() if isinstance(question, str) else ""
    text = original.casefold()
    # Extract before phrase normalisation so operator supplied identifiers
    # retain their exact canonical spelling in the returned duty list.
    found_duties = _extract_duties(original, duties)
    found_roles = _extract_roles(original, role_values)
    for duty in found_duties:
        text = re.sub(_boundary_pattern(duty), "{duty}", text)
    for role in found_roles:
        text = re.sub(_role_pattern(role), "{role}", text)
    return re.sub(r"\s+", " ", text).strip(), found_duties, found_roles


def _target_tokens(question: str) -> list[str]:
    # Duty identifiers in this project are normally D-100 or D-100-test-0.
    # Keep this detector narrow so ordinary prose cannot become an unknown ID.
    tokens = re.findall(r"(?<![\w])(?:[A-Za-z][A-Za-z0-9_]*-[A-Za-z0-9_-]+)(?![\w])", question)
    # Also inspect an explicit target position for arbitrary string IDs.  The
    # modest shape filter avoids treating "for one role" as an unknown ID.
    for match in re.finditer(r"\b(?:for|on|cover(?:age)?|duty(?:\s+id)?|rotation)\s+([^\s,.;!?(){}\[\]\\\"'/:]+)", question):
        token = match.group(1).rstrip("'’")
        if token and (any(char.isdigit() for char in token) or "_" in token or token[:1].isupper()):
            tokens.append(token)
    return list(dict.fromkeys(tokens))


def _unknown_duty(question: str, duties: list[str], found: list[str], roles: list[str] | None = None) -> bool:
    known = set(duties)
    prefixes = {d.casefold().split("-", 1)[0] for d in duties if "-" in d}
    role_tokens = {r.casefold() for r in (roles or ())}
    role_tokens.update(re.sub(r"[_ -]+", " ", r.casefold()) for r in (roles or ()))
    role_tokens.update(re.sub(r"[_ -]+", " ", r.casefold()).split(" ", 1)[0] for r in (roles or ()))
    for token in _target_tokens(question):
        lower = token.casefold()
        if token in known or lower in role_tokens:
            continue
        # Hyphenated prose such as "duty-by-duty" and role spellings such as
        # "first-officer" are not duty identifiers.  Numeric IDs and an
        # unknown ID sharing a known prefix are target-like.
        prefix = lower.split("-", 1)[0]
        if (re.search(r"-[0-9]", lower) or any(char.isdigit() for char in token)
                or prefix in prefixes or "_" in token or token[:1].isupper()):
            return True
    return False


def _has_negation(question: str, start: int) -> bool:
    before = question[:start].casefold()
    # A clause boundary ends the scope of a prior negation.  This accepts
    # "don't assign; show candidates" while preserving "don't show candidates".
    before = re.split(r"[;.!?,]\s*", before)[-1]
    if re.search(r"(?:don't|dont|do\s+not|never|without|no)\s+(?:[a-z0-9_'-]+\s+){0,4}$", before):
        return True
    words = _words(before)
    return "not" in words[-3:] and "do" not in words[-3:]


def _matches(patterns: tuple[str, ...], question: str, positive: bool = True) -> list[re.Match[str]]:
    result: list[re.Match[str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, question.casefold()):
            if positive != (not _has_negation(question, match.start())):
                continue
            result.append(match)
    return result


def _unsafe(value: str) -> bool:
    return any(re.search(pattern, value.casefold()) for pattern in _INJECTION_PATTERNS)


def _mask_known_values(question: str, duty_ids: list[str], roles: list[str]) -> str:
    """Hide supplied identifiers before checking free-form constraints."""

    masked = question
    values = sorted((*duty_ids, *roles), key=lambda value: (-len(value), value.casefold(), value))
    for value in values:
        pattern = _role_pattern(value) if value in roles else _boundary_pattern(value)
        masked = re.sub(pattern, lambda match: " " * len(match.group(0)), masked, flags=re.IGNORECASE)
    return masked


def _unsupported_constraint(question: str, duty_ids: list[str], roles: list[str]) -> tuple[str, str] | None:
    masked = _mask_known_values(question, duty_ids, roles)
    for label, patterns in _UNSUPPORTED_CONSTRAINTS:
        for pattern in patterns:
            # Negative filters such as "no expired certificates" still need
            # unsupported data. Do not reuse action-negation logic here.
            if re.search(pattern, masked, flags=re.IGNORECASE):
                return label, _UNSUPPORTED_REPLIES[label]
    return None


def _writes_requested(question: str) -> bool:
    for pattern in _WRITE_PATTERNS:
        for match in re.finditer(pattern, question.casefold()):
            if not _has_negation(question, match.start()):
                return True
    return False


def _signals(question: str) -> dict[str, int]:
    return {
        "coverage": len(_matches(_COVERAGE_PATTERNS, question)),
        "roster": len(_matches(_ROSTER_PATTERNS, question)),
        "summary": len(_matches(_SUMMARY_PATTERNS, question)),
    }


def _disambiguated_signals(question: str) -> dict[str, int]:
    signals = _signals(question)
    roster_without_schedule = tuple(pattern for pattern in _ROSTER_PATTERNS
                                    if "schedul" not in pattern)
    if (signals["summary"] and signals["roster"]
            and _matches(_SUMMARY_STRONG_PATTERNS, question)
            and not _matches(roster_without_schedule, question)):
        signals["roster"] = 0
    return signals


def _explicit_unknown_role(question: str, roles: list[str], found: list[str]) -> bool:
    if not roles:
        return False
    text = question.casefold()
    # Only inspect phrases that explicitly promise a role.  This keeps words
    # such as "someone" from becoming an invented role.
    role_markers = (
        r"\b(?:as|role|position)\s+(?:an?\s+|the\s+)?([a-z][a-z0-9_-]*)",
        r"\bwhich\s+([a-z][a-z0-9_-]*)\s+(?:could|can|is|are|would)\b",
        r"\b(?:and|or)\s+([a-z][a-z0-9_-]*)\b",
    )
    known = {r.casefold() for r in roles}
    known_variants = {re.sub(r"[_ -]+", " ", r.casefold()) for r in roles}
    known_prefixes = {variant.split(" ", 1)[0] for variant in known_variants if " " in variant}
    ignored = {"a", "an", "the", "slot", "slots", "candidate", "candidates", "crew", "people", "person",
               "on", "for", "as", "in", "at", "of", "to"}
    for marker in role_markers:
        for match in re.finditer(marker, text):
            raw_value = match.group(1)
            # In "D-100 or D-10 as captain", the conjunction marker sees the
            # leading ``D`` of the next duty token.  It is not a role.
            if re.match(r"[a-z]-\d", text[match.start(1):]):
                continue
            value = raw_value.replace("_", " ").replace("-", " ")
            if value not in ignored and value not in known and value not in known_variants and value not in known_prefixes:
                return True
    return False


def _template_parts(template: object) -> tuple[str, str] | None:
    if not isinstance(template, str) or not template.strip() or _unsafe(template):
        return None
    value = re.sub(r"\s+", " ", template.casefold()).strip()
    return value, " ".join(_words(value.replace("{duty}", " ").replace("{role}", " ")))


def _approved_candidates(question: str, duty_ids: list[str], roles: list[str], learned_workflows: Mapping[object, object]) -> tuple[list[dict], dict]:
    duties = _extract_duties(question, duty_ids)
    mentioned_roles = _extract_roles(question, roles)
    signals = _disambiguated_signals(question)
    exact_key = workflow_key(question, duties, roles)[0]
    rows: list[dict] = []
    if not isinstance(learned_workflows, Mapping) or not learned_workflows:
        return rows, {"duties": duties, "roles": mentioned_roles, "signals": signals}
    # A plain mapping has no maintained reverse index.  Scan a fixed prefix in
    # stable insertion order and abstain if that bounded evidence is not safe.
    # Exact templates in the prefix remain fully compatible with old storage;
    # callers with a larger store can promote a compact index later.
    direct_items: list[tuple[object, object]] = []
    marker = object()
    try:
        direct_action = learned_workflows.get(exact_key, marker)
    except (AttributeError, TypeError):
        direct_action = marker
    if direct_action is not marker:
        direct_items.append((exact_key, direct_action))
    items = list(islice(learned_workflows.items(), MAX_WORKFLOW_SCAN + 1))
    scan_truncated = len(items) > MAX_WORKFLOW_SCAN
    seen_items = set()
    for raw_template, raw_action in direct_items + items[:MAX_WORKFLOW_SCAN]:
        item_key = (str(raw_template), repr(raw_action))
        if item_key in seen_items:
            continue
        seen_items.add(item_key)
        action = raw_action if isinstance(raw_action, str) else ""
        if action not in _ACTIONS:
            continue
        parts = _template_parts(raw_template)
        if parts is None:
            continue
        template, template_words = parts
        # Coverage examples must have approved slots.  Roster and summary
        # examples intentionally have no target placeholders.
        if action == "coverage" and _PLACEHOLDERS != set(re.findall(r"\{(?:duty|role)\}", template)):
            continue
        if action != "coverage" and ("{duty}" in template or "{role}" in template):
            continue
        evidence = signals[action]
        exact_example = template == exact_key
        if not evidence and not exact_example:
            continue
        # The approved action is the source of permission to reuse.  The
        # controlled cue is the only generalisation allowed from that example.
        row = {
            "action": action,
            "template": raw_template,
            "provenance": {
                "source": "approved workflow example",
                "template": raw_template,
                "action": action,
                "bounded": True,
            },
        }
        if action == "coverage":
            if len(duties) == 1 and len(mentioned_roles) == 1:
                row.update(duty_id=duties[0], role=mentioned_roles[0])
            else:
                row["targets"] = {"duties": duties, "roles": mentioned_roles}
        rows.append(row)
    rows.sort(key=lambda row: (str(row["template"]).casefold(), str(row["template"])))
    candidate_limit_exceeded = len(rows) > MAX_ROUTE_CANDIDATES
    details = {"duties": duties, "roles": mentioned_roles, "signals": signals,
               "exact_key": exact_key,
               "workflow_scan_truncated": scan_truncated,
               "candidate_limit_exceeded": candidate_limit_exceeded}
    return rows[:MAX_ROUTE_CANDIDATES], details


def candidates(question: str, duty_ids: Iterable[str] | Mapping[str, object], roles: Iterable[str], learned_workflows: Mapping[object, object]) -> list[dict]:
    """Return bounded approved route candidates, including their provenance."""

    duties, role_values = _normalise_inputs(duty_ids, roles)
    if not isinstance(question, str) or not question.strip() or _unsafe(question):
        return []
    guard = guard_request(question, duties, role_values)
    if guard is not None and guard.get("reason") != "unsupported or ambiguous request":
        return []
    rows, _ = _approved_candidates(question, duties, role_values, learned_workflows)
    return rows


def provenance(question: str, duty_ids: Iterable[str] | Mapping[str, object], roles: Iterable[str], learned_workflows: Mapping[object, object]) -> dict:
    """Expose extraction and approved-example evidence for an abstention."""

    duties, role_values = _normalise_inputs(duty_ids, roles)
    safe_question = question if isinstance(question, str) and not _unsafe(question) else ""
    rows, details = _approved_candidates(safe_question, duties, role_values, learned_workflows)
    return {
        "source": "approved workflow examples" if rows else "none",
        "approved_candidates": rows,
        "extracted": {"duties": details["duties"], "roles": details["roles"]},
        "signals": details["signals"],
        "limits": {"max_workflow_scan": MAX_WORKFLOW_SCAN, "max_candidates": MAX_ROUTE_CANDIDATES},
        "truncated": bool(details.get("workflow_scan_truncated") or details.get("candidate_limit_exceeded")),
        "bounded": True,
    }


def guard_request(question: str, duty_ids: Iterable[str] | Mapping[str, object], roles: Iterable[str]) -> dict | None:
    """Return a clarification plan for unsafe, ambiguous, or incomplete input."""

    duties, role_values = _normalise_inputs(duty_ids, roles)
    if not isinstance(question, str) or not question.strip():
        return {"action": "clarify", "reason": "empty request", "reply": "Please describe the read-only information to inspect."}
    text = question.strip()
    if _unsafe(text):
        return {"action": "clarify", "reason": "instruction-like text", "reply": "I can only route a bounded read-only workflow."}
    found_duties = _extract_duties(text, duties)
    found_roles = _extract_roles(text, role_values)
    if _unknown_duty(text, duties, found_duties, role_values):
        return {"action": "clarify", "reason": "unknown duty ID", "reply": "Use one existing duty ID."}
    if _writes_requested(text):
        return {"action": "clarify", "reason": "write request", "reply": "I can inspect coverage, the roster, or a summary; changes need the explicit write workflow."}
    signals = _disambiguated_signals(text)
    positive_actions = [name for name, count in signals.items() if count]
    if len(positive_actions) > 1:
        # A count/total request may mention the schedule as its source.  A
        # concrete roster cue such as "duty-by-duty" still wins the abstention
        # path, while "total ... across the schedule" remains a summary.
        if not (positive_actions == ["summary"]):
            # A negated cue is already removed by _signals, so this is a real
            # request for two operations or a phrase with unclear intent.
            return {"action": "clarify", "reason": "multiple operations", "reply": "Specify one read-only operation: coverage, roster, or summary."}
    # A known target on a whole-workspace operation is a scope mismatch.
    if positive_actions and positive_actions[0] != "coverage" and (found_duties or found_roles):
        return {"action": "clarify", "reason": "multiple targets", "reply": "Roster and summary cover the workspace; use coverage for one duty and role."}
    if positive_actions == ["coverage"]:
        if _explicit_unknown_role(text, role_values, found_roles):
            return {"action": "clarify", "reason": "unknown role", "reply": "Use one existing required role."}
        if len(found_duties) != 1 or len(found_roles) != 1:
            return {"action": "clarify", "reason": "missing or multiple coverage targets", "reply": "Specify one existing duty ID and one required role."}
        unsupported = _unsupported_constraint(text, found_duties, found_roles)
        if unsupported is not None:
            label, reply = unsupported
            return {"action": "clarify", "reason": "unsupported coverage constraints", "constraint": label, "reply": reply}
        return None
    if positive_actions in (["roster"], ["summary"]):
        unsupported = _unsupported_constraint(text, found_duties, found_roles)
        if unsupported is not None:
            label, reply = unsupported
            return {"action": "clarify", "reason": "unsupported coverage constraints", "constraint": label, "reply": reply}
        return None
    unsupported = _unsupported_constraint(text, found_duties, found_roles)
    if unsupported is not None:
        label, reply = unsupported
        return {"action": "clarify", "reason": "unsupported coverage constraints", "constraint": label, "reply": reply}
    # No known operation is a conservative abstention, with an explicit route
    # for the caller to show to the operator.
    return {"action": "clarify", "reason": "unsupported or ambiguous request", "reply": "Specify coverage, roster, or summary."}


def route(question: str, duty_ids: Iterable[str] | Mapping[str, object], roles: Iterable[str], learned_workflows: Mapping[object, object]) -> dict | None:
    """Reuse an approved read-only workflow, or return ``None`` to abstain."""

    duties, role_values = _normalise_inputs(duty_ids, roles)
    guard = guard_request(question, duties, role_values)
    if guard is not None and guard.get("reason") != "unsupported or ambiguous request":
        return None
    rows, details = _approved_candidates(question, duties, role_values, learned_workflows)
    if not rows:
        return None
    only_exact = all(str(row["template"]).casefold().strip() == details.get("exact_key", "") for row in rows)
    if ((details.get("workflow_scan_truncated") and not only_exact)
            or details.get("candidate_limit_exceeded")):
        return None
    actions = {row["action"] for row in rows}
    if len(actions) != 1:
        return None
    action = next(iter(actions))
    if action == "coverage" and (len(details["duties"]) != 1 or len(details["roles"]) != 1):
        return None
    # A candidate collision or conflicting approved correction is an abstention.
    # Same-action templates are retained as evidence, but the chosen template
    # must agree on the extracted operation and arguments.
    rows.sort(key=lambda row: str(row["template"]))
    plan = {"action": action, "provenance": rows[0]["provenance"], "candidates": rows}
    if action == "coverage":
        plan.update(duty_id=details["duties"][0], role=details["roles"][0])
    return plan


# A descriptive alias makes call sites read naturally without duplicating logic.
workflow_candidates = candidates
