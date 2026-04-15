#!/usr/bin/env python3
"""Unit and integration tests for garden_db.py."""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from garden_db import (
    init_db, get_connection, get_schema_version,
    is_pair_checked, get_pair_result, record_pair, load_checked_pairs,
    record_discarded, is_discarded,
    upsert_entry, get_entries_by_domain,
    VALID_RESULTS, SCHEMA_VERSION,
)


class TestGetConnection(unittest.TestCase):

    def test_get_connection_missing_garden_raises(self):
        with self.assertRaises(FileNotFoundError):
            get_connection(Path('/nonexistent/path/garden'))


class TestInitDb(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_garden_db_file(self):
        init_db(self.garden)
        self.assertTrue((self.garden / 'garden.db').exists())

    def test_creates_checked_pairs_table(self):
        init_db(self.garden)
        conn = get_connection(self.garden)
        conn.execute("SELECT * FROM checked_pairs")
        conn.close()

    def test_creates_discarded_entries_table(self):
        init_db(self.garden)
        conn = get_connection(self.garden)
        conn.execute("SELECT * FROM discarded_entries")
        conn.close()

    def test_creates_entries_index_table(self):
        init_db(self.garden)
        conn = get_connection(self.garden)
        conn.execute("SELECT * FROM entries_index")
        conn.close()

    def test_schema_version_set(self):
        init_db(self.garden)
        self.assertEqual(get_schema_version(self.garden), SCHEMA_VERSION)

    def test_idempotent_second_init(self):
        init_db(self.garden)
        init_db(self.garden)
        self.assertEqual(get_schema_version(self.garden), SCHEMA_VERSION)

    def test_no_db_returns_none_schema_version(self):
        self.assertIsNone(get_schema_version(self.garden))

    def test_wal_mode_enabled(self):
        init_db(self.garden)
        conn = get_connection(self.garden)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        self.assertEqual(mode, 'wal')


class TestCheckedPairs(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = Path(self.tmp.name)
        init_db(self.garden)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_pair_not_checked(self):
        self.assertFalse(is_pair_checked(self.garden, 'GE-0001 × GE-0002'))

    def test_recorded_pair_is_checked(self):
        record_pair(self.garden, 'GE-0001 × GE-0002', 'distinct')
        self.assertTrue(is_pair_checked(self.garden, 'GE-0001 × GE-0002'))

    def test_get_pair_result_returns_result(self):
        record_pair(self.garden, 'GE-0001 × GE-0002', 'related', 'cross-ref added')
        self.assertEqual(get_pair_result(self.garden, 'GE-0001 × GE-0002'), 'related')

    def test_get_pair_result_none_for_unknown(self):
        self.assertIsNone(get_pair_result(self.garden, 'GE-9999 × GE-8888'))

    def test_record_pair_idempotent(self):
        record_pair(self.garden, 'GE-0001 × GE-0002', 'distinct')
        record_pair(self.garden, 'GE-0001 × GE-0002', 'distinct')
        conn = get_connection(self.garden)
        count = conn.execute("SELECT COUNT(*) FROM checked_pairs").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_canonical_pair_order_enforced(self):
        record_pair(self.garden, 'GE-0002 × GE-0001', 'distinct')
        self.assertTrue(is_pair_checked(self.garden, 'GE-0001 × GE-0002'))
        self.assertTrue(is_pair_checked(self.garden, 'GE-0002 × GE-0001'))

    def test_invalid_result_raises(self):
        with self.assertRaises(ValueError):
            record_pair(self.garden, 'GE-0001 × GE-0002', 'bogus')

    def test_all_valid_results_accepted(self):
        for i, result in enumerate(sorted(VALID_RESULTS)):
            record_pair(self.garden, f'GE-000{i} × GE-999{i}', result)
            self.assertEqual(get_pair_result(self.garden, f'GE-000{i} × GE-999{i}'), result)

    def test_load_checked_pairs_empty(self):
        self.assertEqual(load_checked_pairs(self.garden), set())

    def test_load_checked_pairs_returns_all(self):
        record_pair(self.garden, 'GE-0001 × GE-0002', 'distinct')
        record_pair(self.garden, 'GE-0003 × GE-0004', 'related')
        pairs = load_checked_pairs(self.garden)
        self.assertIn('GE-0001 × GE-0002', pairs)
        self.assertIn('GE-0003 × GE-0004', pairs)
        self.assertEqual(len(pairs), 2)

    def test_notes_stored(self):
        record_pair(self.garden, 'GE-0001 × GE-0002', 'related', 'cross-referenced both')
        conn = get_connection(self.garden)
        row = conn.execute("SELECT notes FROM checked_pairs").fetchone()
        conn.close()
        self.assertEqual(row[0], 'cross-referenced both')


class TestDiscardedEntries(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = Path(self.tmp.name)
        init_db(self.garden)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_entry_not_discarded(self):
        self.assertFalse(is_discarded(self.garden, 'GE-0001'))

    def test_recorded_entry_is_discarded(self):
        record_discarded(self.garden, 'GE-0001', 'GE-0002', 'subset of GE-0002')
        self.assertTrue(is_discarded(self.garden, 'GE-0001'))

    def test_idempotent(self):
        record_discarded(self.garden, 'GE-0001', 'GE-0002')
        record_discarded(self.garden, 'GE-0001', 'GE-0002')
        conn = get_connection(self.garden)
        count = conn.execute("SELECT COUNT(*) FROM discarded_entries").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_reason_stored(self):
        record_discarded(self.garden, 'GE-0001', 'GE-0002', 'exact duplicate')
        conn = get_connection(self.garden)
        row = conn.execute("SELECT reason FROM discarded_entries").fetchone()
        conn.close()
        self.assertEqual(row[0], 'exact duplicate')


class TestEntriesIndex(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = Path(self.tmp.name)
        init_db(self.garden)
        self.entry = {
            'ge_id': 'GE-20260414-aa0001',
            'title': 'Hibernate @PreUpdate fires at flush time',
            'domain': 'java',
            'type': 'gotcha',
            'score': 12,
            'submitted': '2026-04-14',
            'staleness_threshold': 730,
            'tags': ['hibernate', 'jpa', 'flush'],
            'verified_on': 'hibernate: 6.x',
            'last_reviewed': '',
            'file_path': 'java/GE-20260414-aa0001.md',
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_creates_row(self):
        upsert_entry(self.garden, self.entry)
        rows = get_entries_by_domain(self.garden, 'java')
        self.assertEqual(len(rows), 1)

    def test_upsert_idempotent(self):
        upsert_entry(self.garden, self.entry)
        upsert_entry(self.garden, self.entry)
        rows = get_entries_by_domain(self.garden, 'java')
        self.assertEqual(len(rows), 1)

    def test_get_entries_by_domain_filters_correctly(self):
        upsert_entry(self.garden, self.entry)
        other = {**self.entry, 'ge_id': 'GE-20260414-bb0001', 'domain': 'tools',
                 'file_path': 'tools/GE-20260414-bb0001.md'}
        upsert_entry(self.garden, other)
        self.assertEqual(len(get_entries_by_domain(self.garden, 'java')), 1)
        self.assertEqual(len(get_entries_by_domain(self.garden, 'tools')), 1)

    def test_tags_round_trip_as_list(self):
        upsert_entry(self.garden, self.entry)
        rows = get_entries_by_domain(self.garden, 'java')
        self.assertEqual(rows[0]['tags'], ['hibernate', 'jpa', 'flush'])

    def test_get_entries_ordered_by_score_desc(self):
        low = {**self.entry, 'ge_id': 'GE-20260414-low', 'score': 8,
               'file_path': 'java/GE-20260414-low.md'}
        upsert_entry(self.garden, self.entry)
        upsert_entry(self.garden, low)
        rows = get_entries_by_domain(self.garden, 'java')
        self.assertGreaterEqual(rows[0]['score'], rows[1]['score'])

    def test_empty_domain_returns_empty_list(self):
        self.assertEqual(get_entries_by_domain(self.garden, 'nonexistent'), [])

    def test_upsert_updates_existing(self):
        upsert_entry(self.garden, self.entry)
        upsert_entry(self.garden, {**self.entry, 'title': 'Updated title'})
        rows = get_entries_by_domain(self.garden, 'java')
        self.assertEqual(rows[0]['title'], 'Updated title')

    def test_upsert_missing_ge_id_raises(self):
        with self.assertRaises(ValueError):
            upsert_entry(self.garden, {'title': 'No ID', 'domain': 'java'})

    def test_upsert_empty_ge_id_raises(self):
        with self.assertRaises(ValueError):
            upsert_entry(self.garden, {**self.entry, 'ge_id': ''})

    def test_upsert_non_list_tags_raises(self):
        bad = {**self.entry, 'tags': 'not-a-list'}
        with self.assertRaises(ValueError):
            upsert_entry(self.garden, bad)


if __name__ == '__main__':
    unittest.main(verbosity=2)
