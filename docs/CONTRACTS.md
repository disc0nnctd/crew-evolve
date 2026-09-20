# Scoped import contracts

The contract API makes a reviewed interpretation of a changing export explicit. It is pure Python and uses only the standard library. The public signatures are:

```python
validate_contract(kind, headers, mapping, transforms, source_contract) -> dict
normalize_contract(contract) -> dict
apply_contract(kind, headers, rows, contract) -> list[dict]
fingerprint_contract(contract) -> str
fingerprint_schema(kind, headers, mapping, transforms=None, source_contract=None) -> str
regression_report(before_contract, after_contract, cases) -> dict
```

`kind` is `crew`, `duties`, or `assignments`. `headers` is the exact ordered list from the source file. `mapping` keeps the existing source-column to canonical-field form; a list of source/field pairs is also accepted. Every required field must be mapped once. `source_contract` is a required trimmed name of at most 120 characters. A filename is not a source contract.

The canonical contract has `version`, `kind`, `source_contract`, exact `headers`, `mapping`, and `transforms`. Omitted transforms become explicit `{"op": "identity"}` entries. A contract can be applied only when both its table kind and headers match exactly. The source scope and header list are included in its SHA-256 fingerprint, so a correction for one export family cannot silently transfer to another source shape.

Transforms are keyed by source column and use this closed vocabulary:

```json
{"op": "identity"}
{"op": "boolean", "invert": true}
{"op": "enum", "values": {"raw value": "canonical value"}}
{"op": "datetime", "format": "%Y-%m-%d %H:%M", "timezone": "America/New_York"}
```

Boolean transforms are limited to `available`. A source column named `cannot_work`, `unavailable`, or another known negative-availability spelling cannot use identity; it must declare inversion or an explicit enum. Unknown boolean and enum values fail. Enum transforms apply to scalar fields, while list fields continue to use the existing list parser. Datetimes are limited to `report_at` and `release_at`; the format must declare a complete year/month/day and hour, describes a local time, and the declared IANA timezone supplies its offset. Embedded `%z` and `%Z` directives are rejected. Ambiguous daylight-saving times and nonexistent daylight-saving times fail instead of being guessed. The implementation uses the system `zoneinfo` database; hosts without the required timezone data must install a compatible timezone-data package.

`apply_contract` stages a copy of each raw row and then calls the existing `normalize_records` checks for required fields, identifiers, lists, booleans, duties, and collisions. Each returned record retains lightweight `_source_contract` and `_contract` provenance alongside the normal `_record` field. The source contract is deliberately separate from the dataset filename. Raw rows are never changed in place; the caller keeps the original rows and source text with the imported dataset.

`regression_report` accepts independent cases with `rawheaders` (or `headers`), `rows`, and expected normalized records. It runs both contracts against each case and compares the known expected values. It does not generate expected labels from either contract. A `None` before contract reports no baseline and cannot produce regressions.
