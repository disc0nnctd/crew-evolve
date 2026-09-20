"""Use cases shared by the web API and tests."""

import json
import uuid
import time
import copy
import threading
from collections import OrderedDict

from . import learning
from .data import FIELDS, infer_mapping, normalize_records, parse_table
from .engine import Engine, compare_policy, validate_policy
from .model import Model
from .store import DEMO_POLICY, Store


class App:
    def __init__(self, store, model=None):
        self.store = store
        self.model = model or Model()
        self.cache = OrderedDict()
        self.cache_lock = threading.Lock()
        self.optimization_lock = threading.Lock()
        self.optimization = {"running": False, "message": "No benchmark run yet."}

    def state(self):
        with self.store.connect() as db:
            db.execute("BEGIN")
            datasets = self.store.datasets(db)
            policy = self.store.get(db, "policy")
            engine = Engine(datasets, policy)
            return {"revision": self.store.get(db, "revision"), "policy": policy,
                    "model": self.model.configured, "model_name": self.model.name if self.model.configured else None,
                    "tables": {k: {"source": v["source"], "count": len(v["records"]), "mapping": v["mapping"],
                                   "records": v["records"][:100]} for k, v in datasets.items()},
                    "duties": list(engine.duties.values()), "roles": sorted({c["role"] for c in engine.crew.values()}),
                    "roster": engine.roster(), "learning": learning.history(db),
                    "fields": FIELDS, "learned": self.store.get(db, "learned"),
                    "strategy": self.store.get(db, "strategy"), "benchmark": self.store.get(db, "benchmark"),
                    "optimization": dict(self.optimization),
                    "audit": [dict(r) for r in db.execute("SELECT id,action,created FROM audit ORDER BY id DESC LIMIT 20")]}

    def preview(self, kind, filename, content):
        if kind not in FIELDS:
            raise ValueError("Choose crew, duties, or assignments.")
        headers, rows = parse_table(filename, content)
        with self.store.connect() as db:
            mapping = infer_mapping(kind, headers, self.store.get(db, "learned").get("mappings", {}))
            pending = {"id": uuid.uuid4().hex, "kind": kind, "source": filename.replace("\\", "/").split("/")[-1],
                       "headers": headers, "rows": rows, "mapping": mapping, "original": content}
            db.execute("INSERT INTO imports VALUES (?,?)", (pending["id"], json.dumps(pending)))
            # Bound abandoned uploads without touching accepted source data.
            db.execute("DELETE FROM imports WHERE rowid NOT IN (SELECT rowid FROM imports ORDER BY rowid DESC LIMIT 10)")
        return self.preview_view(pending)

    @staticmethod
    def preview_view(pending):
        try:
            normalize_records(pending["kind"], pending["headers"], pending["rows"], pending["mapping"])
            issue = None
        except ValueError as exc:
            issue = str(exc)
        return {k: pending[k] for k in ("id", "kind", "source", "headers", "mapping")} | {
            "sample": pending["rows"][:5], "count": len(pending["rows"]), "issue": issue,
            "fields": FIELDS[pending["kind"]]}

    @staticmethod
    def pending(db, import_id):
        row = db.execute("SELECT payload FROM imports WHERE id=?", (import_id,)).fetchone()
        if row is None:
            raise ValueError("Import not found. Upload the file again.")
        return json.loads(row[0])

    def analyze(self, import_id):
        with self.store.connect() as db:
            pending = self.pending(db, import_id)
        suggestion = self.model.mapping(pending, FIELDS[pending["kind"]])
        mapping = suggestion.get("mapping")
        if not isinstance(mapping, dict) or any(h not in pending["headers"] or f not in FIELDS[pending["kind"]] for h, f in mapping.items()):
            raise ValueError("Model suggested unknown columns or fields. Review the mapping manually.")
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("Model mapped multiple columns to the same field. Review manually.")
        pending["mapping"] = mapping
        return self.preview_view(pending) | {"uncertainties": suggestion.get("uncertainties", [])}

    def accept_import(self, import_id, mapping, revision):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require_revision(db, revision)
            pending = self.pending(db, import_id)
            records = normalize_records(pending["kind"], pending["headers"], pending["rows"], mapping)
            dataset = {"source": pending["source"], "original": pending["original"], "raw_records": pending["rows"],
                       "mapping": mapping, "records": records}
            db.execute("INSERT OR REPLACE INTO datasets VALUES (?,?)", (pending["kind"], json.dumps(dataset)))
            outcome = learning.learn(self.store, db, {"kind": "mapping", "table": pending["kind"], "headers": pending["headers"], "expected": mapping},
                                     f"Reviewed field mapping for {pending['source']}")
            db.execute("DELETE FROM imports WHERE id=?", (import_id,))
            self.store.audit(db, "import", {"kind": pending["kind"], "source": pending["source"], "records": len(records)})
            return {"revision": self.store.bump(db), "learning": outcome}

    def require_revision(self, db, revision):
        if type(revision) is not int or revision != self.store.get(db, "revision"):
            raise ValueError("The workspace changed. Refresh and review the current data before applying this change.")

    def execute(self, plan):
        if not isinstance(plan, dict):
            raise ValueError("An operation is required.")
        started = time.perf_counter()
        with self.store.connect() as db:
            db.execute("BEGIN")
            revision = self.store.get(db, "revision")
            strategy = self.store.get(db, "strategy")
            key = (revision, json.dumps(plan, sort_keys=True))
            with self.cache_lock:
                if key in self.cache:
                    answer = copy.deepcopy(self.cache[key])
                    self.cache.move_to_end(key)
                    answer["metrics"] = {"cache_hit": True, "strategy": strategy, "engine_ms": round((time.perf_counter() - started) * 1000, 3)}
                    return answer
            engine = Engine(self.store.datasets(db), self.store.get(db, "policy"), strategy)
            action = plan.get("action")
            if action == "coverage":
                result = engine.coverage(plan.get("duty_id"), plan.get("role"))
                count = result['passing']
                subject = "crew member passes" if count == 1 else "crew members pass"
                reply = f"{count} {subject} the configured checks for {plan['duty_id']} / {plan['role']}."
                result["candidate_count"] = len(result["candidates"])
                result["candidates"] = result["candidates"][:100]
                result["truncated"] = result["candidate_count"] > 100
            elif action == "roster":
                result = engine.roster()
                reply = f"{result['open']} open positions; {result['needs_review']} assigned positions need review."
            elif action == "summary":
                result = {"crew": len(engine.crew), "duties": len(engine.duties), "assignments": len(engine.assignments), "roster": engine.roster()}
                reply = f"The workspace contains {result['crew']} crew members and {result['duties']} duties."
            else:
                raise ValueError("Supported operations: coverage, roster, summary.")
            answer = {"action": action, "reply": reply, "result": result, "revision": revision,
                      "plan": {k: plan[k] for k in ("action", "duty_id", "role") if k in plan},
                      "metrics": {"cache_hit": False, "strategy": strategy, "engine_ms": round((time.perf_counter() - started) * 1000, 3)}}
            with self.cache_lock:
                self.cache[key] = copy.deepcopy(answer)
                while len(self.cache) > 16:
                    self.cache.popitem(last=False)
            return answer

    def optimize(self):
        if not self.optimization_lock.acquire(blocking=False):
            raise ValueError("A benchmark is already running.")
        self.optimization = {"running": True, "message": "Starting algorithm comparison…"}

        def run():
            from .optimize import benchmark
            try:
                report = benchmark(progress=lambda message: self.optimization.update(message=message))
                with self.store.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    self.store.put(db, "benchmark", report)
                    if report["correctness_gate"]:
                        self.store.put(db, "strategy", report["selected"])
                        self.store.bump(db)
                    self.store.audit(db, "algorithm_benchmark", {"selected": report["selected"], "passed": report["correctness_gate"]})
                self.optimization = {"running": False, "message": "Benchmark complete. " + ("Best measured algorithm activated." if report["correctness_gate"] else "Correctness gate failed; algorithm unchanged.")}
            except Exception:
                self.optimization = {"running": False, "message": "Benchmark failed. Active algorithm unchanged."}
            finally:
                self.optimization_lock.release()

        threading.Thread(target=run, name="algorithm-benchmark", daemon=True).start()
        return dict(self.optimization)

    def ask(self, question):
        self.validate_question(question)
        with self.store.connect() as db:
            engine = Engine(self.store.datasets(db), self.store.get(db, "policy"))
            roles = sorted({r for d in engine.duties.values() for r in d["required_roles"]})
            key, duties, mentioned_roles = learning.workflow_key(question, engine.duties, roles)
            known = self.store.get(db, "learned").get("workflows", {}).get(key)
            context = {"duties": list(engine.duties.values()), "roles": roles}
        if known:
            plan = {"action": known}
            if known == "coverage":
                if len(duties) != 1 or len(mentioned_roles) != 1:
                    return {"action": "clarify", "reply": "Include one duty ID and one required role so I can check coverage."}
                plan.update(duty_id=duties[0], role=mentioned_roles[0])
            source = "learned workflow"
        else:
            plan = self.model.route(question, context)
            source = "model proposal, checked by the operations engine"
        if plan.get("action") == "clarify":
            return {"action": "clarify", "reply": "I can check coverage for one duty and role, show the roster, or summarize the workspace. Please specify one of these."}
        return self.execute(plan) | {"route_source": source}

    @staticmethod
    def validate_question(question):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
            raise ValueError("Enter a question of at most 2000 characters.")

    def teach(self, question, action):
        self.validate_question(question)
        if action not in ("coverage", "roster", "summary"):
            raise ValueError("Choose coverage, roster, or summary.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            engine = Engine(self.store.datasets(db), self.store.get(db, "policy"))
            roles = {r for d in engine.duties.values() for r in d["required_roles"]}
            key, duties, mentioned_roles = learning.workflow_key(question, engine.duties, roles)
            if action == "coverage" and (len(duties) != 1 or len(mentioned_roles) != 1):
                raise ValueError("A coverage example must name one existing duty ID and one role (use spaces between role words).")
            if action != "coverage" and (duties or mentioned_roles):
                raise ValueError("Roster and summary workflows cover the whole workspace. Use an example without a specific duty or role.")
            result = learning.learn(self.store, db, {"kind": "workflow", "key": key, "action": action}, f"Workflow correction: {question}")
            self.store.audit(db, "workflow_correction", {"question": question, "action": action, "learning": result["id"]})
            return result

    def assign(self, crew_id, duty_id, role, revision):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require_revision(db, revision)
            datasets = self.store.datasets(db)
            engine = Engine(datasets, self.store.get(db, "policy"))
            if engine.integrity():
                raise ValueError("Resolve assignment references before assigning crew.")
            result = engine.check(crew_id, duty_id, role)
            if not result["passes"]:
                raise ValueError("Cannot assign: " + " ".join(result["reasons"]))
            data = datasets.get("assignments", {"source": "Workspace assignments", "mapping": {}, "raw_records": [], "records": []})
            data["records"].append({"crew_id": crew_id, "duty_id": duty_id, "role": role, "_record": None, "_source": "Operator assignment"})
            db.execute("INSERT OR REPLACE INTO datasets VALUES ('assignments',?)", (json.dumps(data),))
            self.store.audit(db, "assign", {"crew_id": crew_id, "duty_id": duty_id, "role": role})
            return {"revision": self.store.bump(db)}

    def unassign(self, duty_id, role, revision):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require_revision(db, revision)
            dataset = self.store.datasets(db).get("assignments")
            if not dataset:
                raise ValueError("No assignments to release.")
            prior = dataset["records"]
            dataset["records"] = [a for a in prior if not (a["duty_id"] == duty_id and a["role"] == role)]
            if len(prior) == len(dataset["records"]):
                raise ValueError("Position is not assigned.")
            db.execute("UPDATE datasets SET payload=? WHERE kind='assignments'", (json.dumps(dataset),))
            self.store.audit(db, "unassign", {"duty_id": duty_id, "role": role})
            return {"revision": self.store.bump(db)}

    def propose_policy(self, policy, reason):
        validate_policy(policy)
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000:
            raise ValueError("Explain why this policy change is proposed.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            before = self.store.get(db, "policy")
            report = compare_policy(self.store.datasets(db), before, policy)
            report["revision"] = self.store.get(db, "revision")
            if not report["checks"]:
                raise ValueError("Import valid crew and duties before comparing policies.")
            cursor = db.execute("INSERT INTO learning(kind,status,reason,before_state,after_state,report) VALUES ('policy','proposed',?,?,?,?)",
                                (reason, json.dumps(before), json.dumps(policy), json.dumps(report)))
            return {"id": cursor.lastrowid, "report": report}

    def suggest_policy(self, request):
        self.validate_question(request)
        with self.store.connect() as db:
            policy = self.store.get(db, "policy")
        suggestion = self.model.policy(request, policy)
        if "policy" not in suggestion:
            return {"question": str(suggestion.get("question") or "Specify the policy values to change.")[:600]}
        return self.propose_policy(suggestion["policy"], suggestion.get("reason", request))

    def activate_policy(self, change_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM learning WHERE id=? AND kind='policy' AND status='proposed'", (change_id,)).fetchone()
            if row is None:
                raise ValueError("Policy proposal not found.")
            report = json.loads(row["report"])
            self.require_revision(db, report["revision"])
            self.store.put(db, "policy", json.loads(row["after_state"]))
            db.execute("UPDATE learning SET status='superseded' WHERE kind='policy' AND status='active'")
            db.execute("UPDATE learning SET status='active' WHERE id=?", (change_id,))
            self.store.audit(db, "policy_activated", {"change_id": change_id})
            return {"revision": self.store.bump(db)}

    def rollback(self, change_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            learning.rollback(self.store, db, change_id)
            return {"ok": True}

    def demo(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent / "examples"
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if self.store.datasets(db):
                raise ValueError("Load the example into an empty workspace only. Your data has not been changed.")
            for kind in ("crew", "duties", "assignments"):
                content = (root / (kind + ".csv")).read_text()
                headers, rows = parse_table(kind + ".csv", content)
                mapping = infer_mapping(kind, headers, {})
                records = normalize_records(kind, headers, rows, mapping)
                data = {"source": "Example: " + kind + ".csv", "original": content, "raw_records": rows, "mapping": mapping, "records": records}
                db.execute("INSERT INTO datasets VALUES (?,?)", (kind, json.dumps(data)))
            self.store.put(db, "policy", DEMO_POLICY)
            self.store.audit(db, "load_example", {})
            return {"revision": self.store.bump(db)}
