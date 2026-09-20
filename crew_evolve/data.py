"""Parse unfamiliar tables without discarding their source values."""

import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import PurePath

MAX_ROWS = 50000
FIELDS = {
    "crew": ["crew_id", "name", "base", "role", "aircraft", "available"],
    "duties": ["duty_id", "report_at", "release_at", "start_base", "end_base", "aircraft", "required_roles"],
    "assignments": ["crew_id", "duty_id", "role"],
}
ALIASES = {
    "crew_id": ["crew_id", "employee_id", "staff_id", "employee_number", "staff_number", "pilot_id"],
    "name": ["name", "full_name", "crew_name", "employee_name"],
    "base": ["base", "home_base", "station"],
    "role": ["role", "rank", "position"],
    "aircraft": ["aircraft", "fleet", "qualifications", "fleet_types", "aircraft_type"],
    "available": ["available", "active", "on_call"],
    "duty_id": ["duty_id", "duty", "rotation_id", "pairing_id"],
    "report_at": ["report_at", "report_time", "start_time", "report_utc"],
    "release_at": ["release_at", "release_time", "end_time", "release_utc"],
    "start_base": ["start_base", "origin", "departure_station"],
    "end_base": ["end_base", "destination", "arrival_station"],
    "required_roles": ["required_roles", "positions", "roles", "crew_required"],
}


def normal(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Times must be text with a timezone, such as 2026-10-01T08:00:00Z.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Invalid timestamp: {value}") from None
    if result.tzinfo is None:
        raise ValueError(f"Timezone missing: {value}. Use Z or an explicit UTC offset.")
    return result.astimezone(timezone.utc)


def parse_table(filename, content):
    if not isinstance(filename, str) or not isinstance(content, str):
        raise ValueError("A filename and text content are required.")
    content = content.lstrip("\ufeff")
    ext = PurePath(filename).suffix.lower()
    if ext in (".csv", ".tsv"):
        try:
            reader = csv.reader(io.StringIO(content), delimiter="\t" if ext == ".tsv" else ",", strict=True)
            headers = next(reader, [])
            if not headers or any(not h.strip() for h in headers) or len(set(headers)) != len(headers):
                raise ValueError("Column names must be nonempty and unique.")
            rows = []
            for cells in reader:
                if not cells:
                    continue
                if len(cells) != len(headers):
                    raise ValueError(f"Record {len(rows) + 1} has {len(cells)} cells; expected {len(headers)}.")
                rows.append(dict(zip(headers, cells)))
                if len(rows) > MAX_ROWS:
                    raise ValueError(f"Import at most {MAX_ROWS} records at a time.")
        except csv.Error as exc:
            raise ValueError(f"Cannot read table: {exc}") from None
    elif ext in (".json", ".jsonl", ".ndjson"):
        try:
            def read_json(text):
                return json.loads(text, parse_constant=lambda x: (_ for _ in ()).throw(ValueError("Non-finite value")))
            rows = [read_json(line) for line in content.splitlines() if line.strip()] if ext != ".json" else read_json(content)
        except (ValueError, RecursionError):
            raise ValueError("Invalid JSON. Supply an array of records or one record per line.") from None
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError("JSON must contain an array of objects.")
        headers = list(dict.fromkeys(k for r in rows for k in r))
    else:
        raise ValueError("Supported files: CSV, TSV, JSON arrays, and JSONL. Export spreadsheets as CSV.")
    if not rows or len(rows) > MAX_ROWS or not headers or len(headers) > 100:
        raise ValueError(f"Supply between 1 and {MAX_ROWS} records with at most 100 columns.")
    if any(not isinstance(h, str) or not normal(h) or len(h) > 160 for h in headers):
        raise ValueError("Use nonempty text column names of at most 160 characters.")
    if len({normal(h) for h in headers}) != len(headers):
        raise ValueError("Some column names differ only in spacing or punctuation. Rename them to avoid ambiguity.")
    return headers, rows


def infer_mapping(kind, headers, learned):
    if kind not in FIELDS:
        raise ValueError("Choose crew, duties, or assignments.")
    result = {}
    for h in headers:
        key = normal(h)
        field = learned.get(kind, {}).get(key)
        if field is None:
            field = next((f for f in FIELDS[kind] if key in ALIASES[f]), None)
        if field:
            result[h] = field
    # Ambiguous source columns never pick a winner by file order.
    return {h: f for h, f in result.items() if list(result.values()).count(f) == 1}


def split_list(value, upper=False):
    values = value if isinstance(value, list) else re.split(r"[|;,]", str(value))
    if any(not isinstance(v, str) for v in values):
        raise ValueError("Lists must contain text.")
    out = [v.strip().upper() if upper else normal(v) for v in values if v.strip()]
    if not out or any(not v for v in out) or len(set(out)) != len(out):
        raise ValueError("Lists must be nonempty and have no duplicates.")
    return out


def normalize_records(kind, headers, rows, mapping):
    if kind not in FIELDS or not isinstance(mapping, dict):
        raise ValueError("Invalid table kind or field mapping.")
    if any(h not in headers or f not in FIELDS[kind] for h, f in mapping.items()):
        raise ValueError("Mapping refers to an unknown column or field.")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Each field must map to exactly one source column.")
    missing = set(FIELDS[kind]) - set(mapping.values())
    if missing:
        raise ValueError("Map required fields: " + ", ".join(sorted(missing)))
    result, seen = [], set()
    for index, raw in enumerate(rows, 1):
        try:
            record = {f: raw.get(h) for h, f in mapping.items()}
            for field, value in list(record.items()):
                if value is None or value == "":
                    raise ValueError(f"{field} is missing")
                if field in ("aircraft", "required_roles"):
                    record[field] = split_list(value, upper=field == "aircraft")
                elif field == "available":
                    if str(value).lower() not in ("true", "false", "yes", "no", "1", "0"):
                        raise ValueError("available must be true/false or yes/no")
                    record[field] = str(value).lower() in ("true", "yes", "1")
                elif field in ("report_at", "release_at"):
                    record[field] = timestamp(value).isoformat()
                else:
                    if not isinstance(value, (str, int)) or isinstance(value, bool):
                        raise ValueError(f"{field} must be text or an identifier")
                    record[field] = str(value).strip()
                    if not record[field] or len(record[field]) > 200:
                        raise ValueError(f"{field} must contain 1–200 characters")
                    if field in ("base", "start_base", "end_base"):
                        record[field] = record[field].upper()
                    if field == "role":
                        record[field] = normal(record[field])
                        if not record[field]:
                            raise ValueError("role must contain letters or numbers")
            if kind == "duties":
                if len(record["aircraft"]) != 1:
                    raise ValueError("a duty must have exactly one aircraft type")
                if timestamp(record["release_at"]) <= timestamp(record["report_at"]):
                    raise ValueError("release must follow report")
            key = (record["crew_id"], record["duty_id"]) if kind == "assignments" else record["crew_id" if kind == "crew" else "duty_id"]
            if key in seen:
                raise ValueError(f"duplicate identifier or assignment: {key}")
            seen.add(key)
            record["_record"] = index
            result.append(record)
        except ValueError as exc:
            raise ValueError(f"Record {index}: {exc}") from None
    if kind == "assignments":
        slots = [(r["duty_id"], r["role"]) for r in result]
        if len(slots) != len(set(slots)):
            raise ValueError("More than one crew member occupies the same duty position.")
    return result
