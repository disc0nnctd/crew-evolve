"""Source-scoped import learning with explicit, replayable evidence.

Evidence is operator-reviewed example meaning, not an independent accuracy score.
Rejections are retained, but never replace a table or activate a contract.
"""
import copy
import hashlib
import json

from .contracts import apply_contract, validate_contract

MAX_EVIDENCE_ROWS = 32
MAX_EVIDENCE_CASES = 128


def scope_key(kind, source_contract, headers):
    if not isinstance(source_contract, str) or not 1 <= len(source_contract.strip()) <= 120:
        raise ValueError("Name the source format (1–120 characters) before learning conversions.")
    return hashlib.sha256(json.dumps([kind, source_contract.strip(), headers], ensure_ascii=False).encode()).hexdigest()


def lookup(learned, kind, source_contract, headers):
    if not source_contract:
        return None
    key = scope_key(kind, source_contract, headers)
    return copy.deepcopy(learned.get("contracts", {}).get(key))


def semantic(records):
    return [{key: value for key, value in record.items() if not key.startswith("_")} for record in records]


def evidence_rows(rows, records, transforms):
    # Include changed value patterns before filling with the first rows. The
    # bounded replay is labelled as such, never presented as complete history.
    indices, seen = [], set()
    for index, row in enumerate(rows):
        signature = json.dumps([row.get(column) for column in sorted(transforms)], sort_keys=True)
        if signature not in seen:
            indices.append(index)
            seen.add(signature)
            if len(indices) == MAX_EVIDENCE_ROWS:
                break
    for index in range(min(len(rows), MAX_EVIDENCE_ROWS)):
        if index not in indices and len(indices) < MAX_EVIDENCE_ROWS:
            indices.append(index)
    return [copy.deepcopy(rows[index]) for index in indices], semantic([records[index] for index in indices])


def passes(contract, case):
    if contract is None:
        return False
    try:
        actual = apply_contract(case["kind"], case["headers"], case["rows"], contract)
        return semantic(actual) == case["expected"]
    except (ValueError, TypeError, KeyError):
        return False


def prepare(store, db, pending, mapping, transforms, source_contract):
    contract = validate_contract(pending["kind"], pending["headers"], mapping, transforms or {}, source_contract)
    records = apply_contract(pending["kind"], pending["headers"], pending["rows"], contract)
    key = scope_key(pending["kind"], source_contract, pending["headers"])
    before = store.get(db, "learned")
    old = before.get("contracts", {}).get(key)
    old_contract = old["contract"] if old else None
    rows, expected = evidence_rows(pending["rows"], records, transforms or {})
    case = {"kind": pending["kind"], "headers": pending["headers"], "rows": rows, "expected": expected}
    cases = [json.loads(row[0]) for row in db.execute("SELECT payload FROM contract_evidence WHERE scope_key=? ORDER BY id LIMIT ?", (key, MAX_EVIDENCE_CASES + 1))]
    if case not in cases:
        if len(cases) >= MAX_EVIDENCE_CASES:
            raise ValueError("This source format reached its 128-import evidence limit. Export the workspace and explicitly review a new source format version; old evidence is retained.")
        cases.append(case)
    elif len(cases) > MAX_EVIDENCE_CASES:
        raise ValueError("This source format exceeds the supported evidence workload.")
    before_results = [passes(old_contract, item) for item in cases]
    after_results = [passes(contract, item) for item in cases]
    failed = [index + 1 for index, result in enumerate(after_results) if not result]
    regressions = [index + 1 for index, (a, b) in enumerate(zip(before_results, after_results)) if a and not b]
    report = {"cases": len(cases), "before_passed": sum(before_results), "after_passed": sum(after_results),
              "regressions": regressions, "failed_cases": failed, "new_correction_passed": passes(contract, case),
              "source_contract": source_contract.strip(), "schema_key": key,
              "scope": "Reviewed examples from this named source format and exact columns; up to 32 diverse rows per import. No claim of unseen-source accuracy.",
              "records_checked": len(records), "evidence_rows": sum(len(item["rows"]) for item in cases),
              "sample": records[:5], "transforms": transforms or {}, "evidence_case_limit": MAX_EVIDENCE_CASES}
    report["failures"] = []
    for number in failed[:5]:
        previous = cases[number - 1]
        try:
            actual = semantic(apply_contract(previous["kind"], previous["headers"], previous["rows"], contract))
            changes = [{"example_row": index + 1, "expected": expected, "candidate": candidate}
                       for index, (expected, candidate) in enumerate(zip(previous["expected"], actual)) if expected != candidate]
            detail = {"case": number, "changed_rows": changes[:5], "changed_count": len(changes)}
        except (ValueError, TypeError, KeyError) as exc:
            detail = {"case": number, "error": str(exc)}
        report["failures"].append(detail)
    report["failure_details_truncated"] = len(failed) > 5
    changed = old_contract != contract
    # Never recycle a historical version after rollback.
    prior = db.execute("SELECT MAX(version) FROM contract_versions WHERE scope_key=?", (key,)).fetchone()[0] or 0
    version = prior + 1 if changed else old["version"]
    report["version"] = version
    status = "rejected" if failed else ("active" if changed else "unchanged")
    after = copy.deepcopy(before)
    after.setdefault("contracts", {})[key] = {"contract": contract, "version": version,
                                             "source_contract": source_contract.strip(), "kind": pending["kind"],
                                             "headers": pending["headers"]}
    return {"status": status, "records": records, "contract": contract, "version": version,
            "key": key, "case": case, "before": before, "after": after, "report": report}


def record(store, db, prepared, reason):
    status = prepared["status"]
    cursor = db.execute("INSERT INTO learning(kind,status,reason,before_state,after_state,report) VALUES ('contract',?,?,?,?,?)",
                        (status, reason, json.dumps(prepared["before"]), json.dumps(prepared["after"]), json.dumps(prepared["report"])))
    if status != "rejected":
        store.put(db, "learned", prepared["after"])
        payload = json.dumps(prepared["case"], sort_keys=True)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        db.execute("INSERT OR IGNORE INTO contract_evidence(scope_key,digest,payload) VALUES (?,?,?)", (prepared["key"], digest, payload))
        if status == "active":
            db.execute("INSERT INTO contract_versions(scope_key,version,learning_id,payload) VALUES (?,?,?,?)",
                       (prepared["key"], prepared["version"], cursor.lastrowid, json.dumps(prepared["contract"])))
    store.audit(db, "contract_" + status, {"change_id": cursor.lastrowid, "source_contract": prepared["report"]["source_contract"], "version": prepared["version"]})
    return {"id": cursor.lastrowid, "status": status, "report": prepared["report"]}
