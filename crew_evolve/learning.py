"""Learning changes configuration, never executable code or operating policy.

Mappings and workflow corrections are replayed against all saved corrections.
A candidate promotes only when the new correction succeeds without regression.
Policy proposals use a separate human-activation path.
"""

import copy
import json

from .data import infer_mapping, normal
from .workflows import workflow_key as bounded_workflow_key


def workflow_key(question, duty_ids, roles):
    return bounded_workflow_key(question, duty_ids, roles)


def evaluate(learned, case):
    if case["kind"] == "mapping":
        actual = infer_mapping(case["table"], case["headers"], learned.get("mappings", {}))
        return all(actual.get(h) == f for h, f in case["expected"].items())
    return learned.get("workflows", {}).get(case["key"]) == case["action"]


def learn(store, db, case, reason):
    before = store.get(db, "learned")
    after = copy.deepcopy(before)
    if case["kind"] == "mapping":
        aliases = after.setdefault("mappings", {}).setdefault(case["table"], {})
        aliases.update({normal(h): f for h, f in case["expected"].items()})
    else:
        after.setdefault("workflows", {})[case["key"]] = case["action"]
    old_cases = [json.loads(r[0]) for r in db.execute("SELECT payload FROM evidence")]
    cases = old_cases + [case]
    old_results = [evaluate(before, c) for c in cases]
    new_results = [evaluate(after, c) for c in cases]
    regressions = [i + 1 for i, (a, b) in enumerate(zip(old_results, new_results)) if a and not b]
    passes = all(new_results) and not regressions
    report = {"cases": len(cases), "before_passed": sum(old_results), "after_passed": sum(new_results),
              "regressions": regressions, "new_correction_passed": new_results[-1],
              "scope": "Replays saved corrections only; does not prove unseen data will be understood."}
    status = "active" if passes else "rejected"
    if after == before:
        status = "unchanged"
    cursor = db.execute("INSERT INTO learning(kind,status,reason,before_state,after_state,report) VALUES (?,?,?,?,?,?)",
                        (case["kind"], status, reason, json.dumps(before), json.dumps(after), json.dumps(report)))
    if passes:
        store.put(db, "learned", after)
        db.execute("INSERT INTO evidence(payload) VALUES (?)", (json.dumps(case),))
    return {"id": cursor.lastrowid, "status": status, "report": report}


def history(db):
    result = []
    for row in db.execute("SELECT * FROM learning ORDER BY id DESC LIMIT 100"):
        item = dict(row)
        for key in ("before_state", "after_state", "report"):
            item[key] = json.loads(item[key])
        result.append(item)
    return result


def rollback(store, db, change_id):
    latest = db.execute("SELECT * FROM learning WHERE status='active' AND kind!='policy' ORDER BY id DESC LIMIT 1").fetchone()
    if latest is None or latest["id"] != change_id:
        raise ValueError("Only the most recent active learning change can be rolled back.")
    store.put(db, "learned", json.loads(latest["before_state"]))
    db.execute("UPDATE learning SET status='rolled_back' WHERE id=?", (change_id,))
    # Keep the evidence: future changes must still satisfy the corrected cases.
    store.audit(db, "learning_rollback", {"change_id": change_id})
