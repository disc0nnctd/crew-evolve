# The data contract

Crew Evolve accepts CSV, TSV, JSON arrays of objects, and JSONL. Excel files
must be exported as one of those formats. Imported files are staged for
preview; the operator reviews the mapping and meaning, tests normalized
records, and then accepts or rejects the replacement.

| Table | Required fields | Meaning |
| --- | --- | --- |
| `crew` | `crew_id`, `name`, `base`, `role`, `aircraft`, `available` | One crew identity, recorded base, role, fleet qualifications, and availability |
| `duties` | `duty_id`, `report_at`, `release_at`, `start_base`, `end_base`, `aircraft`, `required_roles` | One timezone-aware duty block and its required positions |
| `assignments` | `crew_id`, `duty_id`, `role` | One crew member occupying one duty position |

Identifiers preserve leading zeros when supplied as text. Roles become lowercase
underscore words. Aircraft and station values become uppercase. Lists accept
JSON arrays or text separated by `|`, `;`, or `,`; CSV fields containing commas
must be quoted. Availability accepts true/false, yes/no, or 1/0.

The importer rejects duplicate or ambiguous headers, duplicate identifiers or
occupied positions, missing required values, invalid booleans, non-finite JSON
numbers, missing timezones, release-before-report records, and values that do
not pass the field limits. It does not silently choose between columns that
would fill the same field.

## Source-scoped contracts

Legacy imports can use the reviewed field aliases. A learned interpretation
needs a named source scope, such as `staff-export-v1`, and exact ordered source
headers. The contract records the mapping and only these explicit transforms:

- `identity` keeps a value as supplied;
- `boolean` parses availability and can explicitly invert it;
- `enum` maps listed source values to listed canonical values;
- `datetime` parses a declared local format in a declared named timezone.

Negative availability columns such as `cannot_work` cannot silently become
positive availability. The operator must choose an inversion or another
explicit transform. Unknown values and malformed timestamps fail validation.

The import screen's **Test preview** applies the candidate to copied raw rows
and shows normalized samples before replacement. An accepted source contract
is replayed against saved cases before activation. Evidence is deliberately
bounded to 128 reviewed imports per source scope and up to 32 diverse rows per
import. A rejected candidate and its reason remain in learning history.

Contract versions and fingerprints are stored with the scope. Rolling back a
contract changes future reuse only. Existing datasets, original file text, and
raw records remain unchanged. A source with changed columns or changed meaning
must receive a new scope and a new review.

## Retention and references

The workspace keeps original import text, raw rows, normalized records,
mappings, transforms, source scope and version, learning evidence, policy
state, and audit entries. Cross-table references are checked when the engine
queries them, so tables can arrive in any order. Missing crew or duty
references and role mismatches are shown as data issues and block coverage.
Assignments are also checked against the active policy when the roster is
displayed.

The example files use fictional people and a fictional schedule. Their policy
values are illustrative and are not regulatory guidance. Workspace backups
include the retained source material; use the private [backup and restore
commands](WORKSPACE.md) and protect the resulting SQLite files.

The adaptation fixtures and their known answers are a development protocol,
not a production dataset. See [ADAPTATION.md](ADAPTATION.md) for its scope and
limits.
