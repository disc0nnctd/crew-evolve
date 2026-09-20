# Private workspace backup and restore

Crew Evolve keeps one local SQLite workspace. The `crew_evolve.workspace` CLI makes a consistent SQLite backup and restores it into a new data directory. It never contacts the web service or any other service.

```bash
python3 -m crew_evolve.workspace export \
  --data-dir .crew-evolve \
  --destination /path/to/crew-evolve-backup.sqlite

python3 -m crew_evolve.workspace restore \
  --backup /path/to/crew-evolve-backup.sqlite \
  --data-dir /path/to/restored-workspace
```

`backup` is an alias for `export`. The export destination must be a new file. Restore writes only `workspace.sqlite` inside a new or empty destination directory; an existing workspace or nonempty directory is rejected. A failed validation removes its temporary file and leaves the destination untouched.

The backup is a SQLite snapshot of the complete local database. It includes original import text and raw records, normalized datasets, reviewed mappings and source contracts, learning history, evidence, contract versions, policy state, and audit entries. It can contain sensitive operational data from the local workspace. Keep the file private and protect it with the same care as the source workspace.

Before copying, the CLI opens the backup read-only, runs SQLite `integrity_check`, checks the required tables and supported schema version, parses stored JSON, validates policy and normalized datasets, replays declarative import contracts where raw rows are available, and constructs the operations engine. It refuses newer or malformed schemas. The input database is inspected with fixed read-only queries; no SQL from the backup is executed and SQLite extension loading is disabled.

The backup and restore commands are local file operations. They do not upload workspace data, call the configured model provider, or expose a web endpoint.
