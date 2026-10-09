import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from deploy.data_snapshot import snapshot, restore


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data = self.root/'data'
        self.backup = self.root/'backup'
        self.data.mkdir()

    def write(self, name, content):
        path = self.data/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_roundtrip_preserves_filings_and_state_excluding_secrets_and_locks(self):
        body = b'<html><table><tr><td>Financial evidence</td></tr></table></html>'
        digest = hashlib.sha256(body).hexdigest()
        name = 'company/filings/'+digest+'.html'
        self.write(name, body)
        self.write('settings.json', b'{"universe":"niftytotalmarket"}')
        self.write('private/upstox.json', b'{"access_token":"private-fixture"}')
        self.write('company/fundamentals-pull.lock', b'0')
        self.write('locks/scalping_runner.lock', b'\x00')
        self.write('pending.tmp', b'partial')
        snapshot(self.data, self.backup)
        manifest = json.loads((self.backup/'manifest.json').read_text())
        self.assertEqual(manifest['version'], 2)
        self.assertEqual(set(manifest['files']), {'settings.json', name})
        target = self.root/'restored'
        restore(self.backup, target)
        self.assertEqual((target/name).read_bytes(), body)
        self.assertEqual((target/'settings.json').read_bytes(), (self.data/'settings.json').read_bytes())
        self.assertFalse((target/'private').exists())

    def test_legacy_version_one_json_backups_remain_restorable(self):
        self.write('settings.json', b'{"universe":"nifty500"}')
        snapshot(self.data, self.backup)
        manifest = json.loads((self.backup/'manifest.json').read_text())
        manifest['version'] = 1
        (self.backup/'manifest.json').write_text(json.dumps(manifest))
        target = self.root/'legacy'
        restore(self.backup, target)
        self.assertEqual(json.loads((target/'settings.json').read_text()), {'universe':'nifty500'})

    def test_unexpected_html_and_filing_filename_mismatch_are_rejected(self):
        wrong = self.write('report.html', b'<html>Unexpected</html>')
        with self.assertRaisesRegex(ValueError, 'Unexpected file'):
            snapshot(self.data, self.backup)
        wrong.unlink()
        self.write('company/filings/'+'0'*64+'.html', b'<html>Different digest</html>')
        with self.assertRaisesRegex(ValueError, 'Filing checksum mismatch'):
            snapshot(self.data, self.backup)

    def test_credentials_and_corrupt_compressed_filings_are_rejected(self):
        secret = self.write('settings.json', b'{"api_key":"private-fixture"}')
        with self.assertRaisesRegex(ValueError, 'Credential found'):
            snapshot(self.data, self.backup)
        secret.unlink()
        body = b'<html>Public filing</html>'
        digest = hashlib.sha256(body).hexdigest()
        self.write('company/filings/'+digest+'.html', body)
        snapshot(self.data, self.backup)
        (self.backup/'blobs'/(digest+'.html.gz')).write_bytes(gzip.compress(b'<html>Corrupt</html>'))
        with self.assertRaisesRegex(ValueError, 'Corrupt snapshot'):
            restore(self.backup, self.root/'corrupt')

    def test_restore_rejects_path_escape_and_mismatched_filing_digest(self):
        self.backup.mkdir()
        for name in ('../escape.json', 'company/filings/'+'1'*64+'.html'):
            (self.backup/'manifest.json').write_text(json.dumps({'version':2,'files':{name:'0'*64}}))
            with self.assertRaisesRegex(ValueError, 'Unsafe snapshot manifest'):
                restore(self.backup, self.root/'unsafe')


if __name__ == '__main__':
    unittest.main()
