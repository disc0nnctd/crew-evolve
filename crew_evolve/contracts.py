"""Scoped, declarative import contracts.

Contracts make the small amount of interpretation required by an import
explicit and reviewable.  They contain no executable code: transforms are a
closed vocabulary and are applied to a copy of each raw record before the
existing strict normalizer runs.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .data import FIELDS, normal, normalize_records


CONTRACT_VERSION = 1
_SCALAR_FIELDS = {
    field for fields in FIELDS.values() for field in fields
    if field not in {"aircraft", "required_roles"}
}
_NEGATIVE_AVAILABILITY_HEADERS = {
    "cannot_work", "cant_work", "can_not_work", "unavailable",
    "not_available", "inactive", "off_duty", "unfit", "unavailable_flag",
}


def _fail(message: str) -> None:
    raise ValueError(message)


def _json_value(value: Any, label: str) -> Any:
    """Return a detached JSON-safe value, rejecting unstable values."""
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError, RecursionError):
        _fail(f"{label} must be JSON-compatible and finite.")


def _headers(headers: Sequence[str]) -> list[str]:
    if isinstance(headers, (str, bytes)) or not isinstance(headers, Sequence):
        _fail("headers must be an ordered list of column names.")
    result = list(headers)
    if not result or any(not isinstance(h, str) or not h for h in result):
        _fail("headers must contain nonempty text column names.")
    if len(set(result)) != len(result):
        _fail("headers must be unique.")
    return result


def _mapping(mapping: Any, headers: list[str], kind: str) -> dict[str, str]:
    # The existing API uses a source-column -> field dictionary.  Pair lists
    # are accepted as a convenient backwards-compatible serializable form.
    if isinstance(mapping, Mapping):
        items = list(mapping.items())
    elif isinstance(mapping, (list, tuple)):
        items = []
        for item in mapping:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                _fail("mapping pairs must contain source column and field.")
            items.append((item[0], item[1]))
    else:
        _fail("mapping must be a source-column to field mapping.")
    result: dict[str, str] = {}
    for source, field in items:
        if not isinstance(source, str) or not isinstance(field, str):
            _fail("mapping columns and fields must be text.")
        if source not in headers:
            _fail(f"mapping refers to unknown source column: {source}")
        if field not in FIELDS[kind]:
            _fail(f"mapping refers to unknown {kind} field: {field}")
        if source in result:
            _fail(f"mapping repeats source column: {source}")
        result[source] = field
    if len(set(result.values())) != len(result):
        _fail("Each field must map to exactly one source column.")
    missing = set(FIELDS[kind]) - set(result.values())
    if missing:
        _fail("Map required fields: " + ", ".join(sorted(missing)))
    # Preserve header order in the canonical mapping.  This also means the
    # serialized form cannot vary because a caller supplied a different dict
    # insertion order.
    return {source: result[source] for source in headers if source in result}


def _source_contract(value: Any) -> Any:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 120:
        _fail("source_contract must be a trimmed nonempty name of at most 120 characters.")
    return value.strip()


def _check_timezone(value: Any) -> str:
    if not isinstance(value, str) or not value:
        _fail("datetime timezone must be a named timezone.")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        _fail(f"Unknown datetime timezone: {value}")
    return value


def _check_datetime_format(fmt: Any) -> str:
    if not isinstance(fmt, str) or not fmt or "%z" in fmt or "%Z" in fmt:
        _fail("datetime format must be a nonempty local-time format without timezone directives.")
    # Reject unknown strptime directives at contract validation time.  A
    # format may contain arbitrary literal text, so parsing one guessed date
    # is not sufficient to validate its directive vocabulary.
    directives = set(re.findall(r"%([A-Za-z%])", fmt))
    if re.search(r"%(?:[^A-Za-z%]|$)", fmt):
        _fail("datetime format contains an invalid directive.")
    allowed = set("aAbBcdHIjmMpSUVwWxXyYfGgVuvj%")
    if not directives <= allowed:
        _fail("datetime format contains an unsupported directive.")
    if not ({"Y", "y"} & directives) or not ({"m", "b", "B"} & directives) or "d" not in directives:
        _fail("datetime format must declare a year, month, and day.")
    if not ({"H", "I"} & directives):
        _fail("datetime format must declare an hour.")
    return fmt


def _transform(source: str, field: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"transform for {source} must be an object.")
    op = value.get("op")
    if not isinstance(op, str):
        _fail(f"transform for {source} must declare an operation.")
    allowed = {
        "identity": {"op"},
        "boolean": {"op", "invert"},
        "enum": {"op", "values"},
        "datetime": {"op", "format", "timezone"},
    }
    if op not in allowed:
        _fail(f"unsupported transform operation: {op}")
    extra = set(value) - allowed[op]
    if extra:
        _fail(f"unsupported transform keys for {op}: {', '.join(sorted(extra))}")
    if op == "identity":
        if field == "available" and normal(source) in _NEGATIVE_AVAILABILITY_HEADERS:
            _fail(f"{source} expresses negative availability; declare boolean inversion or an explicit enum.")
        return {"op": "identity"}
    if op == "boolean":
        if field != "available":
            _fail("boolean transforms are only allowed for available.")
        if not isinstance(value.get("invert"), bool):
            _fail("boolean transform invert must be true or false.")
        return {"op": "boolean", "invert": value["invert"]}
    if op == "datetime":
        if field not in {"report_at", "release_at"}:
            _fail("datetime transforms are only allowed for report_at or release_at.")
        fmt = _check_datetime_format(value.get("format"))
        # Detect malformed directives now rather than at import time.  A
        # harmless known date exercises the parser without accepting values.
        try:
            datetime.strptime("2000-01-02 03:04:05", fmt)
        except ValueError:
            # Formats may use a different literal date shape, so defer shape
            # validation to actual values while still rejecting non-text.
            pass
        return {"op": "datetime", "format": fmt, "timezone": _check_timezone(value.get("timezone"))}
    # enum
    if field not in _SCALAR_FIELDS:
        _fail("enum transforms are only allowed for scalar fields.")
    values = value.get("values")
    if not isinstance(values, Mapping) or not values:
        _fail("enum transform values must be a nonempty object.")
    canonical: dict[str, str] = {}
    for raw, target in values.items():
        if not isinstance(raw, str) or not isinstance(target, str) or not raw or not target:
            _fail("enum transform keys and values must be nonempty text.")
        if field == "available" and target.casefold() not in {"true", "false", "yes", "no", "1", "0"}:
            _fail("enum values for available must be true/false, yes/no, or 1/0.")
        canonical[raw] = target
    return {"op": "enum", "values": {key: canonical[key] for key in sorted(canonical)}}


def validate_contract(kind: str, headers: Sequence[str], mapping: Any,
                      transforms: Any, source_contract: Any) -> dict[str, Any]:
    """Validate and canonicalize a scoped declarative import contract."""
    if not isinstance(kind, str) or kind not in FIELDS:
        _fail("Choose crew, duties, or assignments.")
    exact_headers = _headers(headers)
    canonical_mapping = _mapping(mapping, exact_headers, kind)
    if transforms is None:
        transforms = {}
    if not isinstance(transforms, Mapping):
        _fail("transforms must be an object keyed by source column.")
    unknown = set(transforms) - set(canonical_mapping)
    if unknown:
        _fail("transforms refer to unmapped source columns: " + ", ".join(sorted(map(str, unknown))))
    canonical_transforms = {}
    for source in canonical_mapping:
        supplied = transforms.get(source, {"op": "identity"})
        canonical_transforms[source] = _transform(source, canonical_mapping[source], supplied)
    return {
        "version": CONTRACT_VERSION,
        "kind": kind,
        "source_contract": _source_contract(source_contract),
        "headers": exact_headers,
        "mapping": canonical_mapping,
        "transforms": canonical_transforms,
    }


def normalize_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an already serialized contract and return its canonical form."""
    if not isinstance(contract, Mapping):
        _fail("contract must be an object.")
    required = {"version", "kind", "source_contract", "headers", "mapping", "transforms"}
    missing = required - set(contract)
    if missing:
        _fail("contract is missing: " + ", ".join(sorted(missing)))
    if contract.get("version") != CONTRACT_VERSION:
        _fail(f"unsupported contract version: {contract.get('version')}")
    return validate_contract(contract["kind"], contract["headers"], contract["mapping"],
                             contract["transforms"], contract["source_contract"])


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def fingerprint_contract(contract: Mapping[str, Any]) -> str:
    """Return a deterministic SHA-256 fingerprint of a canonical contract."""
    canonical = normalize_contract(contract)
    return hashlib.sha256(_canonical_json(canonical).encode("utf-8")).hexdigest()


def fingerprint_schema(kind: str, headers: Sequence[str], mapping: Any,
                       transforms: Any = None, source_contract: Any = None) -> str:
    """Fingerprint schema and interpretation, independent of source scope."""
    canonical = validate_contract(kind, headers, mapping, transforms,
                                  source_contract if source_contract is not None else "schema-only")
    schema = {key: canonical[key] for key in ("version", "kind", "headers", "mapping", "transforms")}
    return hashlib.sha256(_canonical_json(schema).encode("utf-8")).hexdigest()


# Clear aliases for callers that use the noun-first spelling.
contract_fingerprint = fingerprint_contract
schema_fingerprint = fingerprint_schema


def _parse_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text not in {"true", "false", "yes", "no", "1", "0"}:
        _fail("boolean value must be true/false, yes/no, or 1/0")
    return text in {"true", "yes", "1"}


def _parse_datetime(value: Any, fmt: str, zone_name: str) -> str:
    if not isinstance(value, str):
        _fail("datetime values must be text.")
    try:
        local = datetime.strptime(value, fmt)
    except (TypeError, ValueError):
        _fail(f"value does not match datetime format {fmt!r}: {value}")
    if local.tzinfo is not None:
        _fail("datetime format must produce a naive local time.")
    zone = ZoneInfo(zone_name)
    candidates = []
    for fold in (0, 1):
        aware = local.replace(tzinfo=zone, fold=fold)
        roundtrip = aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
        if roundtrip == local:
            candidates.append(aware)
    if not candidates:
        _fail(f"nonexistent local time in {zone_name}: {value}")
    offsets = {candidate.utcoffset() for candidate in candidates}
    if len(offsets) > 1:
        _fail(f"ambiguous local time in {zone_name}: {value}")
    return candidates[0].astimezone(timezone.utc).isoformat()


def _apply_value(value: Any, transform: Mapping[str, Any]) -> Any:
    op = transform["op"]
    if op == "identity":
        return value
    if op == "boolean":
        result = _parse_boolean(value)
        return not result if transform["invert"] else result
    if op == "enum":
        key = value if isinstance(value, str) else str(value)
        values = transform["values"]
        if key not in values:
            _fail(f"unknown enum value: {value}")
        return values[key]
    return _parse_datetime(value, transform["format"], transform["timezone"])


def apply_contract(kind: str, headers: Sequence[str], rows: Iterable[Mapping[str, Any]],
                   contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Apply a contract to raw rows and run the existing strict normalizer."""
    canonical = normalize_contract(contract)
    exact_headers = _headers(headers)
    if kind != canonical["kind"]:
        _fail("contract kind does not match the imported table kind.")
    if exact_headers != canonical["headers"]:
        _fail("source headers do not exactly match this source contract.")
    raw_rows = list(rows)
    staged = []
    for index, raw in enumerate(raw_rows, 1):
        if not isinstance(raw, Mapping):
            _fail(f"Record {index}: rows must contain objects.")
        transformed = dict(raw)
        try:
            for source, transform in canonical["transforms"].items():
                if source in transformed:
                    transformed[source] = _apply_value(transformed[source], transform)
                elif transform["op"] != "identity":
                    _fail(f"{source} is missing")
        except ValueError as exc:
            _fail(f"Record {index}: {exc}")
        staged.append(transformed)
    records = normalize_records(kind, exact_headers, staged, canonical["mapping"])
    source_scope = copy.deepcopy(canonical["source_contract"])
    contract_digest = fingerprint_contract(canonical)
    for index, record in enumerate(records):
        record["_source_contract"] = copy.deepcopy(source_scope)
        record["_contract"] = contract_digest
    return records


def _expected_matches(actual: list[dict[str, Any]], expected: Any) -> bool:
    expected_rows = expected if isinstance(expected, list) else [expected]
    if not isinstance(expected_rows, list) or len(actual) != len(expected_rows):
        return False
    for record, wanted in zip(actual, expected_rows):
        if not isinstance(wanted, Mapping):
            return False
        clean = {key: value for key, value in record.items() if not key.startswith("_")}
        expected_clean = {key: value for key, value in wanted.items() if not str(key).startswith("_")}
        if clean != expected_clean:
            return False
    return True


def _case_parts(case: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    if not isinstance(case, Mapping):
        _fail("regression cases must be objects.")
    headers = case.get("rawheaders", case.get("headers"))
    rows = case.get("rawrows", case.get("rows"))
    expected = case.get("expected", case.get("expected_values"))
    if headers is None or rows is None or expected is None:
        _fail("each regression case needs rawheaders, rows, and expected values.")
    return headers, rows, expected


def regression_report(before_contract: Mapping[str, Any] | None,
                      after_contract: Mapping[str, Any], cases: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate independent known-answer cases against both contract versions."""
    after = normalize_contract(after_contract)
    before = normalize_contract(before_contract) if before_contract is not None else None
    case_list = list(cases)
    before_results: list[bool | None] = []
    after_results: list[bool] = []
    for case in case_list:
        headers, rows, expected = _case_parts(case)
        try:
            after_results.append(_expected_matches(apply_contract(after["kind"], headers, rows, after), expected))
        except (ValueError, TypeError, KeyError):
            after_results.append(False)
        if before is None:
            before_results.append(None)
        else:
            try:
                before_results.append(_expected_matches(apply_contract(before["kind"], headers, rows, before), expected))
            except (ValueError, TypeError, KeyError):
                before_results.append(False)
    regressions = [index + 1 for index, (old, new) in enumerate(zip(before_results, after_results))
                   if old is True and not new]
    return {
        "cases": len(case_list),
        "before_passed": sum(result is True for result in before_results),
        "after_passed": sum(after_results),
        "before_results": before_results,
        "after_results": after_results,
        "regressions": regressions,
        "after_contract": fingerprint_contract(after),
        "scope": "Independent known-answer cases; labels are not generated from either contract.",
    }
