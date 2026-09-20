"""Private, local SQLite workspace export and restore commands.

The commands copy the complete SQLite database, including source imports and
learning evidence.  They never contact the web service and never overwrite a
workspace or backup that already exists.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .contracts import apply_contract, validate_contract
from .data import FIELDS
from .engine import Engine, validate_policy


CURRENT_SCHEMA_VERSION = 2
REQUIRED_TABLES = (
    "state", "imports", "datasets", "learning", "evidence",
    "contract_evidence", "contract_versions", "audit",
)
_JSON_TABLE_COLUMNS = {
    "imports": ("payload",),
    "datasets": ("payload",),
    "learning": ("before_state", "after_state", "report"),
    "evidence": ("payload",),
    "contract_evidence": ("payload",),
    "contract_versions": ("payload",),
    "audit": ("payload",),
}
_STATE_DEFAULTS = {"learned", "revision", "policy", "strategy", "benchmark", "schema_version"}


def _error(message: str) -> None:
    raise ValueError(message)


def _database_path(value: os.PathLike[str] | str) -> Path:
    path = Path(value)
    if path.is_dir():
        path = path / "workspace.sqlite"
    return path


def _readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        _error(f"Workspace database does not exist: {path}")
    try:
        db = sqlite3.connect(f"file:{quote(str(path.resolve()), safe='/')}?mode=ro", uri=True)
        db.enable_load_extension(False)
        db.execute("PRAGMA query_only=ON")
        return db
    except (sqlite3.Error, OSError) as exc:
        _error(f"Cannot open workspace database: {exc}")


def _json(raw: Any, label: str) -> Any:
    if not isinstance(raw, str):
        _error(f"{label} must be JSON text.")
    try:
        return json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON value {value}")))
    except (TypeError, ValueError, RecursionError):
        _error(f"{label} contains invalid JSON.")


def _tables(db: sqlite3.Connection) -> None:
    found = {row[0]: row[1] for row in db.execute(
        "SELECT name, type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    missing = [name for name in REQUIRED_TABLES if found.get(name) != "table"]
    if missing:
        _error("Backup is missing required tables: " + ", ".join(missing))


def _validate_record(kind: str, record: Any, index: int) -> None:
    if not isinstance(record, dict):
        _error(f"Dataset {kind} record {index} must be an object.")
    required = set(FIELDS[kind])
    if not required <= set(record):
        _error(f"Dataset {kind} record {index} is missing normalized fields.")
    for field in required:
        value = record[field]
        if field in {"aircraft", "required_roles"}:
            if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
                _error(f"Dataset {kind} record {index} has an invalid {field} list.")
        elif field == "available":
            if not isinstance(value, bool):
                _error(f"Dataset {kind} record {index} has an invalid available value.")
        elif not isinstance(value, str) or not value or len(value) > 200:
            _error(f"Dataset {kind} record {index} has an invalid {field} value.")
    if "_record" in record and record["_record"] is not None and (
            isinstance(record["_record"], bool) or not isinstance(record["_record"], int) or record["_record"] < 1):
        _error(f"Dataset {kind} record {index} has an invalid provenance index.")


def _validate_dataset(kind: str, data: Any) -> dict[str, Any]:
    if kind not in FIELDS or not isinstance(data, dict):
        _error("Dataset payload has an unknown kind or invalid object.")
    for key in ("source", "raw_records", "mapping", "records"):
        if key not in data:
            _error(f"Dataset {kind} is missing {key}.")
    if "original" not in data:
        if kind == "assignments" and not data["raw_records"] and not data["mapping"]:
            data = dict(data)
            data["original"] = ""
        else:
            _error(f"Dataset {kind} is missing original.")
    if not isinstance(data["source"], str) or not isinstance(data["original"], str):
        _error(f"Dataset {kind} source and original content must be text.")
    raw_rows = data["raw_records"]
    records = data["records"]
    mapping = data["mapping"]
    if not isinstance(raw_rows, list) or not all(isinstance(row, dict) for row in raw_rows):
        _error(f"Dataset {kind} raw_records must be a list of objects.")
    if not isinstance(records, list):
        _error(f"Dataset {kind} records must be a list.")
    for index, record in enumerate(records, 1):
        _validate_record(kind, record, index)
    if kind in ("crew", "duties"):
        identifier = "crew_id" if kind == "crew" else "duty_id"
        values = [record[identifier] for record in records]
        if len(values) != len(set(values)):
            _error(f"Dataset {kind} contains duplicate {identifier} values.")
    else:
        slots = [(record["duty_id"], record["role"]) for record in records]
        if len(slots) != len(set(slots)):
            _error("Dataset assignments contains duplicate duty positions.")
    if not isinstance(mapping, dict):
        _error(f"Dataset {kind} mapping must be an object.")
    transforms = data.get("transforms", {})
    if transforms is None:
        transforms = {}
    if not isinstance(transforms, dict):
        _error(f"Dataset {kind} transforms must be an object.")
    source_contract = data.get("source_contract") or "workspace-validation"
    if not isinstance(source_contract, str):
        _error(f"Dataset {kind} source_contract must be text.")
    contract_version = data.get("contract_version")
    if contract_version is not None and (isinstance(contract_version, bool) or not isinstance(contract_version, int)):
        _error(f"Dataset {kind} contract_version must be an integer or null.")
    # Re-run the declarative contract when the dataset contains enough source
    # information. Operator-created assignment rows can have no raw source or
    # mapping, so their normalized shape is checked above instead.
    if mapping and raw_rows:
        headers = list(raw_rows[0])
        contract = validate_contract(kind, headers, mapping, transforms, source_contract)
        normalized = apply_contract(kind, headers, raw_rows, contract)
        # Assignment/release actions can add or remove operator-managed
        # normalized rows without changing the original imported raw rows.
        # Crew and duty rows have no such mutation path, so their full list
        # must still agree with the imported source.
        if kind != "assignments":
            if len(records) != len(normalized):
                _error(f"Dataset {kind} normalized records do not match raw_records.")
            expected = [{key: value for key, value in record.items() if not key.startswith("_")}
                        for record in records]
            actual = [{key: value for key, value in record.items() if not key.startswith("_")}
                      for record in normalized]
            if actual != expected:
                _error(f"Dataset {kind} normalized records do not match raw_records.")
    return data


def _validate_connection(db: sqlite3.Connection) -> dict[str, Any]:
    db.enable_load_extension(False)
    db.execute("PRAGMA query_only=ON")
    check = db.execute("PRAGMA integrity_check").fetchone()
    if not check or check[0] != "ok":
        _error("Backup failed SQLite integrity_check.")
    _tables(db)
    state = {}
    for key, value in db.execute("SELECT key, value FROM state"):
        if not isinstance(key, str) or key in state:
            _error("State contains invalid or duplicate keys.")
        state[key] = _json(value, f"state {key}")
    missing = _STATE_DEFAULTS - set(state)
    if missing:
        _error("State is missing: " + ", ".join(sorted(missing)))
    schema_version = state["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        _error("schema_version must be an integer.")
    if schema_version > CURRENT_SCHEMA_VERSION:
        _error(f"Backup schema {schema_version} is newer than supported schema {CURRENT_SCHEMA_VERSION}.")
    if schema_version != CURRENT_SCHEMA_VERSION:
        _error(f"Backup schema {schema_version} is not supported by this release.")
    if isinstance(state["revision"], bool) or not isinstance(state["revision"], int) or state["revision"] < 0:
        _error("State revision must be a nonnegative integer.")
    validate_policy(state["policy"])
    if state["strategy"] not in ("reference", "indexed"):
        _error("State contains an unknown coverage strategy.")
    if not isinstance(state["learned"], dict):
        _error("State learned value must be an object.")
    contracts = state["learned"].get("contracts", {})
    if not isinstance(contracts, dict):
        _error("Learned contracts must be an object.")
    for entry in contracts.values():
        if not isinstance(entry, dict) or not isinstance(entry.get("contract"), dict):
            _error("Learned contract entry is invalid.")
        saved_contract = entry["contract"]
        if not {"kind", "headers", "mapping", "transforms", "source_contract"} <= set(saved_contract):
            _error("Learned contract entry is missing required fields.")
        validate_contract(saved_contract["kind"], saved_contract["headers"],
                          saved_contract["mapping"], saved_contract["transforms"],
                          saved_contract["source_contract"])

    datasets = {}
    for kind, payload in db.execute("SELECT kind, payload FROM datasets"):
        if kind in datasets:
            _error(f"Duplicate dataset kind: {kind}")
        datasets[kind] = _validate_dataset(kind, _json(payload, f"dataset {kind}"))
    for table, columns in _JSON_TABLE_COLUMNS.items():
        select = "SELECT " + ", ".join(columns) + " FROM " + table
        for row in db.execute(select):
            for index, column in enumerate(columns):
                _json(row[index], f"{table} {column}")
    try:
        Engine(datasets, state["policy"], state["strategy"])
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        _error(f"Datasets cannot be loaded by the operations engine: {exc}")
    return {"schema_version": schema_version, "datasets": len(datasets),
            "records": sum(len(data["records"]) for data in datasets.values())}


def validate_backup(path: os.PathLike[str] | str) -> dict[str, Any]:
    """Validate a backup without writing to it."""
    db = _readonly(Path(path))
    try:
        return _validate_connection(db)
    except sqlite3.Error as exc:
        _error(f"Backup database is invalid: {exc}")
    finally:
        db.close()


def _new_link(temp_path: Path, destination: Path) -> None:
    try:
        os.link(temp_path, destination)
    except FileExistsError:
        _error(f"Destination already exists: {destination}")


def _backup(source: Path, destination: Path) -> None:
    source_db = _readonly(source)
    temporary = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            _error(f"Destination already exists: {destination}")
        fd, name = tempfile.mkstemp(prefix=".workspace-export-", suffix=".sqlite", dir=str(destination.parent))
        os.close(fd)
        temporary = Path(name)
        target = sqlite3.connect(str(temporary))
        target.enable_load_extension(False)
        try:
            source_db.backup(target)
        finally:
            target.close()
        validate_backup(temporary)
        _new_link(temporary, destination)
    except sqlite3.Error as exc:
        _error(f"Workspace backup failed: {exc}")
    finally:
        source_db.close()
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def export_workspace(source: os.PathLike[str] | str, destination: os.PathLike[str] | str) -> dict[str, Any]:
    """Export a consistent complete workspace to a new backup file."""
    source_path = _database_path(source)
    destination_path = Path(destination)
    if source_path.resolve() == destination_path.resolve():
        _error("Source and destination must be different files.")
    # Validate before creating any destination artifact.
    summary = validate_backup(source_path)
    _backup(source_path, destination_path)
    return {"backup": str(destination_path), **summary}


backup_workspace = export_workspace
export_backup = export_workspace


def restore_workspace(backup: os.PathLike[str] | str, data_dir: os.PathLike[str] | str) -> dict[str, Any]:
    """Restore a validated backup into a new data directory."""
    backup_path = Path(backup)
    destination_dir = Path(data_dir)
    destination = destination_dir / "workspace.sqlite"
    if destination.exists() or destination.is_symlink():
        _error(f"Workspace already exists: {destination}")
    if destination_dir.is_symlink() or (destination_dir.exists() and (not destination_dir.is_dir() or any(destination_dir.iterdir()))):
        _error("Restore destination must be a new or empty data directory.")
    summary = validate_backup(backup_path)
    created_dir = False
    completed = False
    temporary = None
    source_db = None
    try:
        if not destination_dir.exists():
            destination_dir.mkdir(parents=True, exist_ok=False)
            created_dir = True
        source_db = _readonly(backup_path)
        fd, name = tempfile.mkstemp(prefix=".workspace-restore-", suffix=".sqlite", dir=str(destination_dir))
        os.close(fd)
        temporary = Path(name)
        target = sqlite3.connect(str(temporary))
        target.enable_load_extension(False)
        try:
            source_db.backup(target)
        finally:
            target.close()
        validate_backup(temporary)
        _new_link(temporary, destination)
        completed = True
    finally:
        if source_db is not None:
            source_db.close()
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        if created_dir and not completed:
            try:
                destination_dir.rmdir()
            except OSError:
                # Never remove files or a directory that another actor added
                # after this invocation created the directory.
                pass
    return {"workspace": str(destination), **summary}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export or restore a private local Crew Evolve workspace.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("export", "backup"):
        command = sub.add_parser(name, help="copy a workspace to a new SQLite backup")
        command.add_argument("--data-dir", default=".crew-evolve")
        command.add_argument("--destination", required=True)
    command = sub.add_parser("restore", help="restore a backup into a new data directory")
    command.add_argument("--backup", required=True)
    command.add_argument("--data-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command in ("export", "backup"):
            result = export_workspace(Path(args.data_dir) / "workspace.sqlite", args.destination)
        else:
            result = restore_workspace(args.backup, args.data_dir)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, sqlite3.Error, TypeError, ValueError, KeyError) as exc:
        print(f"crew-evolve workspace: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
