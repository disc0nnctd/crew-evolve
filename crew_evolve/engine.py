"""Duty-block coverage under explicit policies, without model arithmetic.

Passing these checks is not a claim of regulatory compliance. Duty blocks are
supplied by the operator, not reconstructed from individual flight legs.
"""

from datetime import timedelta
import math
from bisect import bisect_right
from collections import defaultdict

from .data import timestamp


def validate_policy(policy):
    required = {"min_rest_hours", "max_duty_hours", "max_7day_hours", "label"}
    if not isinstance(policy, dict) or set(policy) != required:
        raise ValueError("Policy requires a label, min_rest_hours, max_duty_hours, and max_7day_hours.")
    for key, maximum in (("min_rest_hours", 72), ("max_duty_hours", 24), ("max_7day_hours", 168)):
        value = policy[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
            raise ValueError(f"{key} must be greater than zero and at most {maximum}.")
    if policy["max_7day_hours"] < policy["max_duty_hours"]:
        raise ValueError("The weekly limit cannot be below the single-duty limit.")
    if not isinstance(policy["label"], str) or not 1 <= len(policy["label"].strip()) <= 200:
        raise ValueError("Give the policy a label of at most 200 characters.")
    return policy


def hours(start, end):
    return (end - start).total_seconds() / 3600


def rolling_peak(intervals, start, end, strategy):
    endpoints = {b for a, b in intervals} | {a + timedelta(days=7) for a, b in intervals}
    endpoints = [t for t in endpoints if t > start and t - timedelta(days=7) < end]
    if strategy == "reference":
        return max((sum(max(0, hours(max(a, t - timedelta(days=7)), min(b, t))) for a, b in intervals)
                    for t in endpoints), default=0)
    # Integrate a sweep-line of duty start/end events once. Each rolling sum
    # becomes two binary searches rather than a scan over the entire history.
    events = defaultdict(int)
    for a, b in intervals:
        events[a] += 1
        events[b] -= 1
    times = sorted(events)
    cumulative, rates, total, rate = [], [], 0.0, 0
    previous = times[0]
    for point in times:
        total += hours(previous, point) * rate
        cumulative.append(total)
        rate += events[point]
        rates.append(rate)
        previous = point

    def integral(point):
        i = bisect_right(times, point) - 1
        return 0 if i < 0 else cumulative[i] + hours(times[i], point) * rates[i]

    return max((integral(t) - integral(t - timedelta(days=7)) for t in endpoints), default=0)


class Engine:
    def __init__(self, datasets, policy, strategy="indexed"):
        if strategy not in ("reference", "indexed"):
            raise ValueError("Unknown coverage algorithm.")
        self.strategy = strategy
        self.datasets = datasets
        self.policy = validate_policy(policy)
        self.crew = {r["crew_id"]: r for r in datasets.get("crew", {}).get("records", [])}
        self.duties = {r["duty_id"]: r for r in datasets.get("duties", {}).get("records", [])}
        self.assignments = datasets.get("assignments", {}).get("records", [])
        self.by_crew, self.by_slot = defaultdict(list), defaultdict(list)
        if strategy == "indexed":
            for a in self.assignments:
                self.by_crew[a["crew_id"]].append(a)
                self.by_slot[(a["duty_id"], a["role"])].append(a)

    def integrity(self):
        issues = []
        for a in self.assignments:
            c, d = self.crew.get(a["crew_id"]), self.duties.get(a["duty_id"])
            if c is None or d is None:
                issues.append(f"Assignment references missing crew or duty: {a['crew_id']} / {a['duty_id']}.")
            elif a["role"] != c["role"] or a["role"] not in d["required_roles"]:
                issues.append(f"Assignment role mismatch: {a['crew_id']} / {a['duty_id']}.")
        return issues

    def source(self, kind, record):
        return {"file": record.get("_source", self.datasets.get(kind, {}).get("source", "workspace")),
                "record": record.get("_record"), "kind": kind}

    def check(self, crew_id, duty_id, role, existing=False):
        if crew_id not in self.crew or duty_id not in self.duties:
            raise ValueError("Unknown crew member or duty.")
        c, d = self.crew[crew_id], self.duties[duty_id]
        if role not in d["required_roles"]:
            raise ValueError("That position is not required on this duty.")
        reasons = []
        if not c["available"]:
            reasons.append("Marked unavailable.")
        if c["role"] != role:
            reasons.append(f"Role is {c['role']}; this position requires {role}.")
        if d["aircraft"][0] not in c["aircraft"]:
            reasons.append(f"No recorded qualification for {d['aircraft'][0]}.")
        occupied = self.by_slot[(duty_id, role)] if self.strategy == "indexed" else [a for a in self.assignments if a["duty_id"] == duty_id and a["role"] == role]
        if occupied and not (existing and occupied[0]["crew_id"] == crew_id):
            reasons.append("This position is already assigned.")
        start, end = timestamp(d["report_at"]), timestamp(d["release_at"])
        duration = hours(start, end)
        if duration > self.policy["max_duty_hours"]:
            reasons.append(f"Duty is {duration:g} hours; policy limit is {self.policy['max_duty_hours']:g}.")
        assignments = self.by_crew[crew_id] if self.strategy == "indexed" else self.assignments
        other = [self.duties[a["duty_id"]] for a in assignments
                 if a["crew_id"] == crew_id and a["duty_id"] != duty_id and a["duty_id"] in self.duties]
        sources = [self.source("crew", c), self.source("duties", d)]
        sources += [self.source("duties", x) for x in other]
        previous, following = [], []
        for duty in other:
            a, b = timestamp(duty["report_at"]), timestamp(duty["release_at"])
            if start < b and a < end:
                reasons.append(f"Overlaps duty {duty['duty_id']}.")
            elif b <= start:
                gap = hours(b, start)
                previous.append((b, duty))
                if gap < self.policy["min_rest_hours"]:
                    reasons.append(f"Rest after {duty['duty_id']} is {gap:g} hours; minimum is {self.policy['min_rest_hours']:g}.")
            elif a >= end:
                gap = hours(end, a)
                following.append((a, duty))
                if gap < self.policy["min_rest_hours"]:
                    reasons.append(f"Rest before {duty['duty_id']} is {gap:g} hours; minimum is {self.policy['min_rest_hours']:g}.")
        location = max(previous, key=lambda x: x[0])[1]["end_base"] if previous else c["base"]
        if location != d["start_base"]:
            reasons.append(f"Last recorded location is {location}; duty starts at {d['start_base']}. Positioning is not modeled.")
        if following:
            next_duty = min(following, key=lambda x: x[0])[1]
            if d["end_base"] != next_duty["start_base"]:
                reasons.append(f"Duty ends at {d['end_base']}; next duty starts at {next_duty['start_base']}.")
        intervals = [(timestamp(x["report_at"]), timestamp(x["release_at"])) for x in other] + [(start, end)]
        # Sliding sums can peak at any interval end or start plus seven days.
        # Include future duties so adding a duty cannot break a later window.
        peak = round(rolling_peak(intervals, start, end, self.strategy), 8)
        if peak > self.policy["max_7day_hours"]:
            reasons.append(f"A rolling seven-day window reaches {peak:g} duty hours; limit is {self.policy['max_7day_hours']:g}.")
        return {"crew_id": crew_id, "name": c["name"], "base": c["base"], "role": c["role"],
                "passes": not reasons, "reasons": reasons, "duty_hours": round(duration, 4),
                "peak_7day_hours": round(peak, 4), "sources": sources}

    def coverage(self, duty_id, role):
        if not self.crew or not self.duties:
            raise ValueError("Import crew and duties before checking coverage.")
        issues = self.integrity()
        if issues:
            raise ValueError("Resolve roster data issues first: " + " ".join(issues[:5]))
        candidates = [self.check(cid, duty_id, role) for cid in self.crew]
        candidates.sort(key=lambda c: (not c["passes"], c["peak_7day_hours"], c["name"], c["crew_id"]))
        return {"duty": self.duties[duty_id], "role": role, "candidates": candidates,
                "passing": sum(c["passes"] for c in candidates), "policy": self.policy,
                "basis": "Qualified and available, duty length, rest on both sides, overlap, recorded location, rolling duty hours.",
                "limits": "Only imported duty history is checked. No certification expiry, leave windows, positioning, flight-time limits, or jurisdiction rules are inferred."}

    def roster(self):
        issues = self.integrity()
        slots = []
        for d in sorted(self.duties.values(), key=lambda x: timestamp(x["report_at"])):
            for role in d["required_roles"]:
                occupied = self.by_slot[(d["duty_id"], role)] if self.strategy == "indexed" else [a for a in self.assignments if a["duty_id"] == d["duty_id"] and a["role"] == role]
                a = occupied[0] if occupied else None
                crew = self.crew.get(a["crew_id"]) if a else None
                check = self.check(crew["crew_id"], d["duty_id"], role, existing=True) if crew else None
                slots.append({"duty_id": d["duty_id"], "role": role, "report_at": d["report_at"],
                              "release_at": d["release_at"], "start_base": d["start_base"], "end_base": d["end_base"],
                              "crew_id": a["crew_id"] if a else None, "name": crew["name"] if crew else None,
                              "state": "open" if not a else "needs_review" if not check or not check["passes"] else "assigned",
                              "reasons": check["reasons"] if check else [], "source": self.source("duties", d)})
        return {"slots": slots, "issues": issues, "open": sum(s["state"] == "open" for s in slots),
                "needs_review": sum(s["state"] == "needs_review" for s in slots)}


def compare_policy(datasets, before, after):
    validate_policy(after)
    old, new = Engine(datasets, before), Engine(datasets, after)
    count = len(old.crew) * sum(len(d["required_roles"]) for d in old.duties.values())
    if count > 50000:
        raise ValueError("Interactive policy comparisons are limited to 50,000 candidate checks. Compare a scoped schedule before proposing this policy.")
    changes = []
    if not old.integrity():
        for duty in old.duties.values():
            for role in duty["required_roles"]:
                for cid in old.crew:
                    existing = any(a["crew_id"] == cid and a["duty_id"] == duty["duty_id"] and a["role"] == role for a in old.assignments)
                    a = old.check(cid, duty["duty_id"], role, existing)
                    b = new.check(cid, duty["duty_id"], role, existing)
                    if a["passes"] != b["passes"]:
                        changes.append({"crew_id": cid, "duty_id": duty["duty_id"], "role": role,
                                        "before": a["passes"], "after": b["passes"], "assigned": existing,
                                        "reasons": b["reasons"]})
    return {"checks": len(old.crew) * sum(len(d["required_roles"]) for d in old.duties.values()) if not old.integrity() else 0,
            "changes": changes, "new_assignment_failures": sum(c["assigned"] and not c["after"] for c in changes),
            "data_issues": old.integrity(), "note": "Comparison against current data, not proof of regulatory compliance. Requires human activation."}
