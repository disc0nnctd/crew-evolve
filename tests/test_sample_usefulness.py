import unittest

from scripts.sample_usefulness import (
    CASE_SPEC_HASH,
    CASE_SPEC_VERSION,
    derive_pairing_duties,
    expected_captains,
    project_crew_rows,
)


class SampleUsefulnessProjectionTests(unittest.TestCase):
    def setUp(self):
        self.crew = [
            {"crew_id": "C-3310", "name": "D. Reddy", "rank": "Captain", "base": "BLR", "ratings": ["A320"], "status": "active"},
            {"crew_id": "C-2091", "name": "H. Naidu", "rank": "Captain", "base": "BLR", "ratings": ["ATR72"], "status": "active"},
            {"crew_id": "C-2210", "name": "S. Kapoor", "rank": "Captain", "base": "DEL", "ratings": ["A320"], "status": "active"},
            {"crew_id": "C-4000", "name": "On Leave", "rank": "Captain", "base": "BLR", "ratings": ["A320"], "status": "leave"},
        ]
        self.rosters = {
            "pairings": [
                {
                    "pairing_id": "P-X",
                    "days": [
                        {
                            "date": "2026-09-15",
                            "flights": ["F1", "F2"],
                            "report_utc": "2026-09-15T06:00:00Z",
                            "release_utc": "2026-09-15T15:30:00Z",
                        },
                        {
                            "date": "2026-09-16",
                            "flights": ["F3", "F4"],
                            "report_utc": "2026-09-16T04:00:00Z",
                            "release_utc": "2026-09-16T14:45:00Z",
                        },
                    ],
                }
            ]
        }
        self.flights = [
            {"flight_id": "F1", "aircraft_type": "A320", "dep_station": "BLR", "arr_station": "BOM"},
            {"flight_id": "F2", "aircraft_type": "A320", "dep_station": "BOM", "arr_station": "DEL"},
            {"flight_id": "F3", "aircraft_type": "A320", "dep_station": "DEL", "arr_station": "BLR"},
            {"flight_id": "F4", "aircraft_type": "A320", "dep_station": "BLR", "arr_station": "CCU"},
        ]

    def test_projection_keeps_source_ids_and_explicit_status_fields(self):
        rows = project_crew_rows(self.crew)
        self.assertEqual([row["crew_id"] for row in rows], ["C-3310", "C-2091", "C-2210", "C-4000"])
        self.assertEqual(rows[-1]["status"], "leave")
        self.assertEqual(rows[0]["ratings"], "A320")

    def test_expected_filter_is_independent_and_scoped(self):
        duty = derive_pairing_duties(self.rosters, self.flights, "P-X")[0]
        self.assertEqual(expected_captains(self.crew, duty, 12), ["C-3310"])
        self.assertEqual(duty["start_base"], "BLR")
        self.assertEqual(duty["end_base"], "DEL")

    def test_pairing_days_are_separate_supplied_blocks(self):
        duties = derive_pairing_duties(self.rosters, self.flights, "P-X")
        self.assertEqual([d["duty_id"] for d in duties], ["P-X-2026-09-15", "P-X-2026-09-16"])
        self.assertEqual(duties[1]["start_base"], "DEL")

    def test_case_spec_is_versioned(self):
        self.assertEqual(CASE_SPEC_VERSION, "sample-usefulness-1")
        self.assertEqual(len(CASE_SPEC_HASH), 64)


if __name__ == "__main__":
    unittest.main()
