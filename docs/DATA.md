# The data contract

Crew Evolve accepts differently named columns and normalizes them into these tables. Field names are reviewable; record meanings remain the operator's responsibility. Formats are CSV, TSV, JSON arrays of objects, and JSONL. Excel should be exported as CSV. PDFs and arbitrary documents are not supported yet.

| Table | Required fields | Meaning |
| --- | --- | --- |
| crew | crew_id, name, base, role, aircraft, available | Unique crew identity, recorded location fallback, one role, fleet qualifications, current availability |
| duties | duty_id, report_at, release_at, start_base, end_base, aircraft, required_roles | One duty block, timezone-aware timestamps, exactly one fleet type, one required position per listed role |
| assignments | crew_id, duty_id, role | One crew member occupying one required position |

Lists accept JSON arrays or text separated by `|`, `;`, or `,`. CSV fields containing commas must be quoted. Roles are normalized to lowercase words separated by underscores. Aircraft and station values become uppercase. Availability accepts true/false, yes/no, or 1/0. Identifiers preserve leading zeros when supplied as text.

The importer rejects duplicate or ambiguous headers, duplicate crew/duty IDs, duplicate assignments or occupied positions, missing required values, invalid boolean values, non-finite JSON numbers, missing timezones, and release-before-report records. It never silently chooses between columns that map to the same field.

Imports are staged first. Accepting the mapping validates every row and replaces one table in a transaction. Source text and raw records are retained along with the mapping and normalized records. Unmapped columns survive in the source, even though the operating engine does not use them.

Cross-table references are checked at query time so tables can arrive in any order. Missing crew/duty references and role mismatches are visible data issues and block coverage. Assignments are also checked against current policy when the roster is displayed.

The example files use fictional people and a fictional schedule. Example policy values are not regulatory guidance.
