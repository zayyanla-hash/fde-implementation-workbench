"""Persistence and optimistic concurrency checks, using temporary databases."""
import tempfile
import unittest
from pathlib import Path

from workbench.onboarding_store import OnboardingStore, RevisionConflict, StorageError


class OnboardingStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'nested' / 'state.sqlite3'

    def test_save_reload_and_independent_stores(self):
        store = OnboardingStore(self.path)
        self.assertEqual(store.read()['revision'], 0)
        def change(state):
            state['revision'] += 1
            state['activity'].append({'at': '2026-10-14T00:00:00Z', 'action': 'test', 'details': 'Saved'})
            return state
        result = store.change(0, change)
        self.assertEqual(result['revision'], 1)
        self.assertEqual(OnboardingStore(self.path).read(), result)
        result['activity'].clear()
        self.assertEqual(len(store.read()['activity']), 1)

    def test_stale_revision_and_failed_mutation_preserve_data(self):
        store = OnboardingStore(self.path)
        def change(state):
            state['revision'] = 1
            return state
        store.change(0, change)
        with self.assertRaises(RevisionConflict):
            store.change(0, change)
        def fail(state):
            state['revision'] = 99
            raise ValueError('failed validation')
        with self.assertRaises(ValueError):
            store.change(1, fail)
        self.assertEqual(store.read()['revision'], 1)

    def test_corrupt_existing_database_is_reported_not_reset(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b'not sqlite data')
        with self.assertRaises(StorageError):
            OnboardingStore(self.path).read()
        self.assertEqual(self.path.read_bytes(), b'not sqlite data')

    def test_corrupt_snapshot_fields_are_reported_without_reset(self):
        import json
        import sqlite3
        from contextlib import closing
        store = OnboardingStore(self.path)
        state = store.read()
        state['tasks'] = [{}]
        with closing(sqlite3.connect(self.path)) as database:
            with database:
                database.execute('UPDATE onboarding SET data=? WHERE id=1', (json.dumps(state),))
        with self.assertRaises(StorageError):
            store.read()
        with closing(sqlite3.connect(self.path)) as database:
            self.assertEqual(json.loads(database.execute('SELECT data FROM onboarding').fetchone()[0]), state)

    def test_two_writers_using_same_revision_cannot_overwrite(self):
        import concurrent.futures
        a, b = OnboardingStore(self.path), OnboardingStore(self.path)
        a.read()
        def update(store):
            def change(state):
                state['revision'] += 1
                return state
            try:
                store.change(0, change)
                return 'saved'
            except RevisionConflict:
                return 'stale'
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            outcomes = list(pool.map(update, (a, b)))
        self.assertCountEqual(outcomes, ['saved', 'stale'])
        self.assertEqual(a.read()['revision'], 1)
