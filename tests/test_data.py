import unittest

from crew_evolve.data import infer_mapping, normalize_records, parse_table


class ImportTests(unittest.TestCase):
    def test_csv_quotes_and_leading_zero_identifiers_survive(self):
        text = 'crew_id,name,base,role,aircraft,available\n001,"Rao, Asha",DEL,captain,A320|B737,yes\n'
        headers, rows = parse_table('crew.csv', text)
        records = normalize_records('crew', headers, rows, infer_mapping('crew', headers, {}))
        self.assertEqual(records[0]['crew_id'], '001')
        self.assertEqual(records[0]['name'], 'Rao, Asha')
        self.assertEqual(records[0]['aircraft'], ['A320', 'B737'])

    def test_bad_structure_is_rejected(self):
        for filename, content in [('x.csv', 'a,a\n1,2'), ('x.csv', 'staff-id,staff id\n1,2'),
                                  ('x.csv', 'a,b\n1'), ('x.json', '{}'), ('x.json', '[{"x":NaN}]'),
                                  ('x.xlsx', 'binary'), ('x.csv', 'a\n')]:
            with self.subTest(filename=filename, content=content), self.assertRaises(ValueError):
                parse_table(filename, content)

    def test_no_silent_field_collisions(self):
        self.assertEqual(infer_mapping('crew', ['crew_id', 'employee_id'], {}), {})

    def test_learned_alias_is_scoped_to_table(self):
        learned = {'crew': {'badge': 'crew_id'}}
        self.assertEqual(infer_mapping('crew', ['Badge'], learned), {'Badge': 'crew_id'})
        self.assertEqual(infer_mapping('assignments', ['Badge'], learned), {})

    def test_timezone_and_order_are_required(self):
        for report, release in [('2026-10-01T08:00:00', '2026-10-01T09:00:00Z'),
                                ('2026-10-01T10:00:00Z', '2026-10-01T09:00:00Z')]:
            headers, rows = parse_table('duties.csv', 'duty_id,report_at,release_at,start_base,end_base,aircraft,required_roles\n' +
                                       f'D1,{report},{release},DEL,DEL,A320,captain\n')
            with self.assertRaises(ValueError):
                normalize_records('duties', headers, rows, infer_mapping('duties', headers, {}))

    def test_missing_values_and_duplicate_assignments_fail(self):
        for text in ['crew_id,duty_id,role\nC1,D1,captain\nC2,D1,captain',
                     'crew_id,duty_id,role\nC1,D1,']:
            h, r = parse_table('assignments.csv', text)
            with self.assertRaises(ValueError):
                normalize_records('assignments', h, r, infer_mapping('assignments', h, {}))

    def test_jsonl_and_tsv(self):
        for filename, content in [('x.jsonl', '{"a":1}\n{"a":2}'), ('x.tsv', 'a\n1\n2')]:
            h, rows = parse_table(filename, content)
            self.assertEqual(h, ['a'])
            self.assertEqual(len(rows), 2)
