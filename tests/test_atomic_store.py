import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.research import store, jobs


class AtomicStoreTests(unittest.TestCase):
    def test_transient_replace_lock_retries_without_exposing_partial_state(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(store, 'DATA', Path(directory)):
            store.write('checkpoint', {'cash': 123})
            replace = Path.replace
            attempts = []
            def busy_then_replace(source, destination):
                attempts.append(source)
                self.assertEqual(store.read('checkpoint'), {'cash': 123})
                if len(attempts) < 3:
                    raise PermissionError('File busy')
                return replace(source, destination)
            with patch.object(Path, 'replace', busy_then_replace), patch.object(store.time, 'sleep') as sleep:
                store.write('checkpoint', {'cash': 456})
            self.assertEqual(len(attempts), 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(store.read('checkpoint'), {'cash': 456})
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_persistent_lock_preserves_previous_checkpoint_and_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(store, 'DATA', Path(directory)):
            store.write('checkpoint', {'cash': 123})
            with patch.object(Path, 'replace', side_effect=PermissionError('File busy')) as replace, patch.object(store.time, 'sleep'):
                with self.assertRaises(PermissionError):
                    store.write('checkpoint', {'cash': 456})
            self.assertEqual(replace.call_count, 5)
            self.assertEqual(store.read('checkpoint'), {'cash': 123})
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_job_diagnostic_omits_exception_message_and_secrets(self):
        try:
            raise OSError('Bearer sensitive-token https://secret-url')
        except OSError as error:
            message = jobs.failure_detail(error)
        self.assertIn('OSError at test_atomic_store.py:', message)
        self.assertNotIn('sensitive-token', message)
        self.assertNotIn('secret-url', message)
