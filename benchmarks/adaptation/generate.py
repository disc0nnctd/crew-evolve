"""Generate the checked-in adaptation benchmark fixtures.

Only the standard library is used.  The generator is deterministic and is
safe to rerun when the fixture protocol changes; the resulting manifest stores
SHA-256 fingerprints for every input and label file.
"""

from __future__ import annotations

import csv
import copy
import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FAMILY_ROOT = ROOT / "families"
LABEL_ROOT = ROOT / "labels"
SCHEMA_VERSION = "adaptation-v2"


VARIANTS = [
    ("train_01_canonical", "train", "canonical", 101),
    ("train_02_aliases", "train", "aliases", 203),
    ("train_03_cannot_work", "train", "cannot_work", 307),
    ("train_04_enum", "train", "enum", 401),
    ("train_05_eu_dates", "train", "eu_dates", 509),
    ("train_06_faults", "train", "canonical_faults", 601),
    ("development_01_polarity", "development", "polarity", 701),
    ("development_02_enum_dates", "development", "enum_dates", 809),
    ("development_03_faults", "development", "faults", 907),
    ("final_v2_01_neg_enum", "final", "v2_neg_enum", 1301),
    ("final_v2_02_local_dates", "final", "v2_local_dates", 1409),
    ("final_v2_03_mixed_relations", "final", "v2_mixed", 1511),
]


def _canonical(seed: int) -> dict[str, list[dict[str, str]]]:
    """Create related tables; IDs, names, and dates all depend on ``seed``."""

    stamp = datetime(2026, 10, 1, 6, tzinfo=timezone.utc) + timedelta(days=seed % 17)
    tag = str(seed)
    crew = [
        {"crew_id": f"C-{tag}-01", "name": "Asha Rao", "base": "DEL",
         "role": "captain", "aircraft": "A320", "available": "true"},
        {"crew_id": f"C-{tag}-02", "name": "Noor Khan", "base": "DEL",
         "role": "first_officer", "aircraft": "A320", "available": "true"},
        {"crew_id": f"C-{tag}-03", "name": "Mira Sen", "base": "BOM",
         "role": "captain", "aircraft": "A320", "available": "false"},
    ]
    duties = []
    for index, roles in ((1, "captain|first_officer"), (2, "captain")):
        report = stamp + timedelta(days=index - 1)
        release = report + timedelta(hours=8)
        duties.append({
            "duty_id": f"D-{tag}-{index:02d}",
            "report_at": report.isoformat().replace("+00:00", "Z"),
            "release_at": release.isoformat().replace("+00:00", "Z"),
            "start_base": "DEL", "end_base": "DEL", "aircraft": "A320",
            "required_roles": roles,
        })
    assignments = [
        {"crew_id": crew[0]["crew_id"], "duty_id": duties[0]["duty_id"], "role": "captain"},
        {"crew_id": crew[1]["crew_id"], "duty_id": duties[0]["duty_id"], "role": "first_officer"},
    ]
    return {"crew": crew, "duties": duties, "assignments": assignments}


def _format_time(value: str, style: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if style in {"eu_dates", "combined"}:
        return parsed.strftime("%d/%m/%Y %H:%M")
    if style == "enum_dates":
        return parsed.strftime("%Y/%m/%d %H:%MZ")
    if style == "unavailable":
        return parsed.strftime("%Y-%m-%d %H:%M:%S+00:00")
    if style == "v2_neg_enum":
        return parsed.strftime("%Y.%m.%d %H:%M")
    if style == "v2_local_dates":
        return parsed.strftime("%d-%m-%Y %H:%M")
    if style == "v2_mixed":
        return parsed.strftime("%Y%m%d-%H%M")
    return value


def _source_tables(canonical: dict[str, list[dict[str, str]]], style: str):
    """Return source rows, mapping, and declarative transforms."""

    configs = {
        "canonical": {
            "crew": {"crew_id": "crew_id", "name": "name", "base": "base", "role": "role", "aircraft": "aircraft", "available": "available"},
            "duties": {"duty_id": "duty_id", "report_at": "report_at", "release_at": "release_at", "start_base": "start_base", "end_base": "end_base", "aircraft": "aircraft", "required_roles": "required_roles"},
            "assignments": {"crew_id": "crew_id", "duty_id": "duty_id", "role": "role"},
        },
        "aliases": {
            "crew": {"Employee number": "crew_id", "Full name": "name", "Home base": "base", "Rank": "role", "Fleet types": "aircraft", "On call": "available"},
            "duties": {"Rotation ID": "duty_id", "Report time": "report_at", "Release time": "release_at", "Origin": "start_base", "Destination": "end_base", "Fleet": "aircraft", "Positions": "required_roles"},
            "assignments": {"Employee number": "crew_id", "Rotation ID": "duty_id", "Position": "role"},
        },
        "cannot_work": {
            "crew": {"Badge": "crew_id", "Person": "name", "Home station": "base", "Position": "role", "Fleet types": "aircraft", "Cannot work": "available"},
            "duties": {"Pairing": "duty_id", "Report UTC": "report_at", "Release UTC": "release_at", "From": "start_base", "To": "end_base", "Aircraft type": "aircraft", "Crew required": "required_roles"},
            "assignments": {"Badge": "crew_id", "Pairing": "duty_id", "Position": "role"},
        },
        "enum": {
            "crew": {"Staff No": "crew_id", "Legal name": "name", "Base code": "base", "Crew position": "role", "Equipment": "aircraft", "Availability flag": "available"},
            "duties": {"Duty code": "duty_id", "Sign on": "report_at", "Sign off": "release_at", "Start": "start_base", "Finish": "end_base", "Fleet code": "aircraft", "Required positions": "required_roles"},
            "assignments": {"Staff No": "crew_id", "Duty code": "duty_id", "Crew position": "role"},
        },
        "eu_dates": {
            "crew": {"Staff ID": "crew_id", "Display name": "name", "Station": "base", "Rank name": "role", "Fleet": "aircraft", "Available code": "available"},
            "duties": {"Rotation": "duty_id", "Report local": "report_at", "Release local": "release_at", "Departure": "start_base", "Arrival": "end_base", "Aircraft": "aircraft", "Roles": "required_roles"},
            "assignments": {"Staff ID": "crew_id", "Rotation": "duty_id", "Rank name": "role"},
        },
        "canonical_faults": {
            "crew": {"crew_id": "crew_id", "name": "name", "base": "base", "role": "role", "aircraft": "aircraft", "available": "available"},
            "duties": {"duty_id": "duty_id", "report_at": "report_at", "release_at": "release_at", "start_base": "start_base", "end_base": "end_base", "aircraft": "aircraft", "required_roles": "required_roles"},
            "assignments": {"crew_id": "crew_id", "duty_id": "duty_id", "role": "role"},
        },
    }
    if style in {"polarity", "v2_mixed"}:
        base_style = "cannot_work"
    elif style == "unavailable":
        base_style = "canonical"
    elif style in {"enum_dates", "v2_neg_enum"}:
        base_style = "enum"
    elif style in {"combined"}:
        base_style = "enum"
    elif style in {"faults", "contradictions"}:
        base_style = "canonical_faults"
    elif style == "v2_local_dates":
        base_style = "aliases"
    else:
        base_style = style
    mapping = copy.deepcopy(configs[base_style])
    if style == "unavailable":
        mapping["crew"] = {("Unavailable" if source == "available" else source): field
                            for source, field in mapping["crew"].items()}
    if style == "v2_neg_enum":
        renames = {"Availability flag": "Cannot work status", "Crew position": "Role code"}
        mapping["crew"] = {renames.get(source, source): field for source, field in mapping["crew"].items()}
        mapping["assignments"] = {"Role code" if source == "Crew position" else source: field
                                   for source, field in mapping["assignments"].items()}
    elif style == "v2_local_dates":
        renames = {"On call": "Call status", "Report time": "Report stamp", "Release time": "Release stamp"}
        mapping = {kind: {renames.get(source, source): field for source, field in field_map.items()}
                   for kind, field_map in mapping.items()}
    elif style == "v2_mixed":
        renames = {"Cannot work": "Unavailable code", "Report UTC": "Report mark", "Release UTC": "Release mark"}
        mapping = {kind: {renames.get(source, source): field for source, field in field_map.items()}
                   for kind, field_map in mapping.items()}
    rows: dict[str, list[dict[str, str]]] = {}
    transforms: dict[str, dict[str, dict]] = {"crew": {}, "duties": {}, "assignments": {}}
    for kind, field_map in mapping.items():
        out = []
        for source_row in canonical[kind]:
            row = {}
            for header, field in field_map.items():
                value = source_row[field]
                if field in {"report_at", "release_at"}:
                    value = _format_time(value, style)
                elif field == "available":
                    if style in {"cannot_work", "polarity", "v2_mixed"}:
                        value = "false" if value == "true" else "true"
                    elif style in {"enum", "enum_dates", "combined"}:
                        value = {"true": "1", "false": "0"}[value]
                    elif style == "v2_neg_enum":
                        value = {"true": "no", "false": "yes"}[value]
                    elif style == "eu_dates":
                        value = {"true": "1", "false": "0"}[value]
                    elif style == "unavailable":
                        value = {"true": "no", "false": "yes"}[value]
                    elif style == "aliases":
                        value = {"true": "yes", "false": "no"}[value]
                elif field == "role" and style in {"enum", "enum_dates", "combined"}:
                    value = {"captain": "CAP", "first_officer": "FO"}[value]
                elif field == "role" and style == "v2_neg_enum":
                    value = {"captain": "CPT", "first_officer": "FO"}[value]
                elif field in {"aircraft", "required_roles"} and style in {"enum", "enum_dates", "combined", "v2_neg_enum"}:
                    value = value.replace("|", ";")
                row[header] = value
            out.append(row)
        rows[kind] = out
        # Transform keys are source headers. They are explicit, so a reviewer
        # can inspect exactly what feedback teaches.
        for header, field in field_map.items():
            if field == "available":
                transforms[kind][header] = {"op": "boolean", "invert": style in {"cannot_work", "polarity", "unavailable", "v2_neg_enum", "v2_mixed"}}
            elif field == "role" and style in {"enum", "enum_dates", "combined"}:
                transforms[kind][header] = {"op": "enum", "values": {"CAP": "captain", "FO": "first_officer"}}
            elif field == "role" and style == "v2_neg_enum":
                transforms[kind][header] = {"op": "enum", "values": {"CPT": "captain", "FO": "first_officer"}}
            elif field in {"report_at", "release_at"} and style in {"eu_dates", "enum_dates", "unavailable", "combined", "v2_neg_enum", "v2_local_dates", "v2_mixed"}:
                fmt = {"eu_dates": "%d/%m/%Y %H:%M", "enum_dates": "%Y/%m/%d %H:%MZ", "unavailable": "%Y-%m-%d %H:%M:%S+00:00", "combined": "%d/%m/%Y %H:%M", "v2_neg_enum": "%Y.%m.%d %H:%M", "v2_local_dates": "%d-%m-%Y %H:%M", "v2_mixed": "%Y%m%d-%H%M"}[style]
                transforms[kind][header] = {"op": "datetime", "format": fmt, "timezone": "UTC"}
    # Include irrelevant metadata in some exports to ensure it is not treated
    # as a business field or a hidden label.
    if style in {"enum", "enum_dates", "combined", "v2_neg_enum"}:
        for row in rows["crew"]:
            row["Export note"] = "night-roster"
    return rows, mapping, transforms


def _canonical_expected(canonical):
    expected = {}
    for kind, rows in canonical.items():
        normalized = []
        for row in rows:
            item = dict(row)
            if kind in {"crew"}:
                item["available"] = item["available"] == "true"
                item["aircraft"] = [item["aircraft"]]
            elif kind == "duties":
                item["report_at"] = item["report_at"].replace("Z", "+00:00")
                item["release_at"] = item["release_at"].replace("Z", "+00:00")
                item["aircraft"] = [item["aircraft"]]
                item["required_roles"] = item["required_roles"].split("|")
            normalized.append(item)
        expected[kind] = normalized
    return expected


def _availability_value(style: str, available: bool) -> str:
    if style in {"cannot_work", "polarity", "v2_mixed"}:
        return "false" if available else "true"
    if style in {"unavailable", "v2_neg_enum"}:
        return "no" if available else "yes"
    if style in {"enum", "enum_dates", "combined", "eu_dates"}:
        return "1" if available else "0"
    if style in {"aliases", "v2_local_dates"}:
        return "yes" if available else "no"
    return "true" if available else "false"


def _labels(name, split, style, seed, canonical, mapping, transforms):
    crew_id = canonical["crew"][0]["crew_id"]
    duty_id = canonical["duties"][0]["duty_id"]
    expected = _canonical_expected(canonical)
    crew_id_source = next(source for source, field in mapping["crew"].items() if field == "crew_id")
    duty_id_source = next(source for source, field in mapping["duties"].items() if field == "duty_id")
    assignment_crew_source = next(source for source, field in mapping["assignments"].items() if field == "crew_id")
    assignment_duty_source = next(source for source, field in mapping["assignments"].items() if field == "duty_id")
    crew_available = next(source for source, field in mapping["crew"].items() if field == "available")
    crew_role = next(source for source, field in mapping["crew"].items() if field == "role")
    assignment_role = next(source for source, field in mapping["assignments"].items() if field == "role")
    crew_name_source = next(source for source, field in mapping["crew"].items() if field == "name")
    contradictory_role = {"enum": "CAP", "enum_dates": "CAP", "combined": "CAP",
                          "v2_neg_enum": "CPT"}.get(style, "captain")
    missing_reason = "missing"
    future_cases = []
    for index in range(1, 25):
        future = copy.deepcopy(expected)
        changes = [{"kind": "crew", "row": 1, "field": crew_name_source,
                    "value": f"Scenario {index}"}]
        future["crew"][1]["name"] = f"Scenario {index}"
        if index % 4 == 0:
            future_id = f"C-{seed}-F{index:02d}"
            future["crew"][0]["crew_id"] = future_id
            future["assignments"][0]["crew_id"] = future_id
            changes.extend([
                {"kind": "crew", "row": 0, "field": crew_id_source, "value": future_id},
                {"kind": "assignments", "row": 0, "field": assignment_crew_source, "value": future_id},
            ])
        elif index % 4 == 1:
            future_duty_id = f"D-{seed}-F{index:02d}"
            future["duties"][1]["duty_id"] = future_duty_id
            changes.append({"kind": "duties", "row": 1, "field": duty_id_source, "value": future_duty_id})
        elif index % 4 == 2:
            report = datetime.fromisoformat(canonical["duties"][1]["report_at"].replace("Z", "+00:00")) + timedelta(days=index)
            release = datetime.fromisoformat(canonical["duties"][1]["release_at"].replace("Z", "+00:00")) + timedelta(days=index)
            report_z = report.isoformat().replace("+00:00", "Z")
            release_z = release.isoformat().replace("+00:00", "Z")
            report_source = next(source for source, field in mapping["duties"].items() if field == "report_at")
            release_source = next(source for source, field in mapping["duties"].items() if field == "release_at")
            future["duties"][1]["report_at"] = report.isoformat()
            future["duties"][1]["release_at"] = release.isoformat()
            changes.extend([
                {"kind": "duties", "row": 1, "field": report_source, "value": _format_time(report_z, style)},
                {"kind": "duties", "row": 1, "field": release_source, "value": _format_time(release_z, style)},
            ])
        else:
            desired = not future["crew"][2]["available"]
            future["crew"][2]["available"] = desired
            changes.append({"kind": "crew", "row": 2, "field": crew_available,
                            "value": _availability_value(style, desired)})
        future_cases.append({"id": f"future_values_{index:02d}", "kind": "all",
                             "scenario": True, "mutation": {"changes": changes},
                             "expected": {"accepted": True, "records": future}})
    unknown_accept = style not in {"enum", "enum_dates", "combined", "v2_neg_enum"}
    unknown_expected = copy.deepcopy(expected)
    unknown_expected["crew"][0]["role"] = "unknown_role"
    return {
        "schema_version": SCHEMA_VERSION,
        "family": name,
        "split": split,
        "seed": seed,
        "source_contract": f"{name}:v2",
        "mapping": mapping,
        "transforms": transforms,
        "expected": {
            "valid": {"accepted": True, "records": expected, "relationships": {"crew": 3, "duties": 2, "assignments": 2}},
            "availability": {crew_id: True, canonical["crew"][1]["crew_id"]: True, canonical["crew"][2]["crew_id"]: False},
            "coverage": {"duty_id": duty_id, "role": "captain", "eligible": [crew_id]},
        },
        "cases": [
            {"id": "valid", "kind": "all", "expected": {"accepted": True}},
            {"id": "valid_replay", "kind": "all", "expected": {"accepted": True}},
            *future_cases,
            {"id": "missing_value", "kind": "crew", "mutation": {"row": 1, "field": crew_available, "value": ""},
             "expected": {"accepted": False, "reason": missing_reason,
                          "allowed_reasons": ["missing", "invalid_boolean"]}},
            {"id": "duplicate_identifier", "kind": "crew", "mutation": {"duplicate_row": 0}, "expected": {"accepted": False, "reason": "duplicate"}},
            {"id": "contradictory_assignment", "kind": "assignments", "mutation": {"row": 1, "field": assignment_role, "value": contradictory_role}, "expected": {"accepted": False, "reason": "contradiction"}},
            {"id": "unknown_enum", "kind": "crew", "mutation": {"row": 0, "field": crew_role, "value": "UNKNOWN_ROLE"},
             "expected": ({"accepted": True, "records": unknown_expected} if unknown_accept
                          else {"accepted": False, "reason": "unknown_enum"})},
        ],
    }


def _write_csv(path: Path, rows: list[dict[str, str]]):
    headers = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def generate() -> dict:
    if FAMILY_ROOT.exists():
        shutil.rmtree(FAMILY_ROOT)
    if LABEL_ROOT.exists():
        shutil.rmtree(LABEL_ROOT)
    FAMILY_ROOT.mkdir(parents=True)
    LABEL_ROOT.mkdir(parents=True)
    families = []
    for name, split, style, seed in VARIANTS:
        canonical = _canonical(seed)
        rows, mapping, transforms = _source_tables(canonical, style)
        family_dir = FAMILY_ROOT / name
        family_dir.mkdir()
        files = {}
        for kind in ("crew", "duties", "assignments"):
            path = family_dir / f"{kind}.csv"
            _write_csv(path, rows[kind])
            files[f"{kind}.csv"] = _sha256(path)
        labels = _labels(name, split, style, seed, canonical, mapping, transforms)
        label_path = LABEL_ROOT / f"{name}.json"
        label_path.write_text(json.dumps(labels, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        families.append({"name": name, "split": split, "seed": seed, "style": style,
                         "files": files, "labels": f"labels/{name}.json",
                         "labels_sha256": _sha256(label_path)})
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": "2.0",
        "description": "Source-format adaptation benchmark; labels are outside model input.",
        "splits": {"train": 6, "development": 3, "final": 3},
        "budgets": [0, 1, 5, 10, 20],
        "seeds": [11, 23, 37, 41, 53],
        "families": families,
        "labels_are_model_input": False,
        "final_status": "v2 holdout reserved; no final evaluation included",
        "retired_final_v1": "history/manifest-v1-retired.json",
    }
    manifest_path = ROOT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    result = generate()
    print(json.dumps({"families": len(result["families"]), "splits": result["splits"]}, sort_keys=True))
