import unittest
import copy

from crew_evolve.contracts import (
    apply_contract,
    fingerprint_contract,
    fingerprint_schema,
    regression_report,
    validate_contract,
)


CREW_HEADERS = ["badge", "person", "station", "position", "fleet", "cannot_work"]
CREW_MAPPING = {
    "badge": "crew_id",
    "person": "name",
    "station": "base",
    "position": "role",
    "fleet": "aircraft",
    "cannot_work": "available",
}


def crew_contract(source="export-v1"):
    return validate_contract(
        "crew",
        CREW_HEADERS,
        CREW_MAPPING,
        {"cannot_work": {"op": "boolean", "invert": True}},
        source,
    )


class ContractTests(unittest.TestCase):
    def test_inversion_survives_later_records_and_keeps_source_provenance(self):
        contract = crew_contract()
        rows = [
            {"badge": "001", "person": "Asha", "station": "DEL", "position": "captain",
             "fleet": "A320", "cannot_work": "false"},
            {"badge": "002", "person": "Noor", "station": "BOM", "position": "first officer",
             "fleet": "A320", "cannot_work": "true"},
        ]
        original = copy.deepcopy(rows)
        records = apply_contract("crew", CREW_HEADERS, rows, contract)
        self.assertEqual([record["available"] for record in records], [True, False])
        self.assertEqual(rows, original)
        self.assertEqual(records[0]["_source_contract"], "export-v1")
        self.assertEqual(records[0]["_contract"], fingerprint_contract(contract))

    def test_wrong_headers_cannot_reuse_scoped_contract(self):
        contract = crew_contract()
        with self.assertRaisesRegex(ValueError, "exactly match"):
            apply_contract("crew", ["badge2"] + CREW_HEADERS[1:], [{"badge2": "x"}], contract)

    def test_negative_header_requires_explicit_transform(self):
        with self.assertRaisesRegex(ValueError, "negative availability"):
            validate_contract("crew", CREW_HEADERS, CREW_MAPPING, {}, "export-v1")

    def test_unknown_values_and_wrong_operations_reject(self):
        with self.assertRaisesRegex(ValueError, "unknown enum value"):
            contract = validate_contract(
                "crew", CREW_HEADERS, CREW_MAPPING,
                {"cannot_work": {"op": "enum", "values": {"Y": "true", "N": "false"}}},
                "export-v1",
            )
            apply_contract("crew", CREW_HEADERS, [
                {"badge": "1", "person": "A", "station": "DEL", "position": "captain",
                 "fleet": "A320", "cannot_work": "maybe"}
            ], contract)
        with self.assertRaisesRegex(ValueError, "only allowed for available"):
            validate_contract("crew", CREW_HEADERS, CREW_MAPPING,
                              {"person": {"op": "boolean", "invert": False}}, "export-v1")

    def test_datetime_rejects_ambiguous_and_nonexistent_local_times(self):
        headers = ["duty", "report", "release", "from", "to", "plane", "roles"]
        mapping = {"duty": "duty_id", "report": "report_at", "release": "release_at",
                   "from": "start_base", "to": "end_base", "plane": "aircraft", "roles": "required_roles"}
        transforms = {
            "report": {"op": "datetime", "format": "%Y-%m-%d %H:%M", "timezone": "America/New_York"},
            "release": {"op": "datetime", "format": "%Y-%m-%d %H:%M", "timezone": "America/New_York"},
        }
        contract = validate_contract("duties", headers, mapping, transforms, "ops-v2")
        base = {"duty": "D1", "from": "DEL", "to": "DEL", "plane": "A320", "roles": "captain"}
        with self.assertRaisesRegex(ValueError, "nonexistent"):
            apply_contract("duties", headers, [dict(base, report="2026-03-08 02:30", release="2026-03-08 04:00")], contract)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            apply_contract("duties", headers, [dict(base, report="2026-11-01 01:30", release="2026-11-01 04:00")], contract)

    def test_fingerprints_are_order_independent_for_mapping_input(self):
        one = crew_contract(" export-v1 ")
        two = validate_contract("crew", CREW_HEADERS, list(reversed(list(CREW_MAPPING.items()))),
                                {"cannot_work": {"op": "boolean", "invert": True}},
                                "export-v1")
        self.assertEqual(fingerprint_contract(one), fingerprint_contract(two))
        self.assertEqual(fingerprint_schema("crew", CREW_HEADERS, CREW_MAPPING,
                                            {"cannot_work": {"op": "boolean", "invert": True}},
                                            "export-v1"),
                         fingerprint_schema("crew", CREW_HEADERS, CREW_MAPPING,
                                            {"cannot_work": {"op": "boolean", "invert": True}},
                                            "different-source"))

    def test_regression_report_uses_independent_known_answers(self):
        after = crew_contract()
        rows = [{"badge": "001", "person": "Asha", "station": "DEL", "position": "captain",
                 "fleet": "A320", "cannot_work": "true"}]
        report = regression_report(None, after, [{"rawheaders": CREW_HEADERS, "rows": rows,
                                                  "expected": [{"crew_id": "001", "name": "Asha", "base": "DEL",
                                                                "role": "captain", "aircraft": ["A320"],
                                                                "available": False, "_record": 1}]}])
        self.assertEqual(report["after_passed"], 1)
        self.assertEqual(report["regressions"], [])


if __name__ == "__main__":
    unittest.main()
