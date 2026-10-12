import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from PIL import Image
from engine_bom import webapp
from engine_bom.changedetect import extract_text, align_and_diff


class ReviewFixes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = {'kind': 'bom', 'status': 'done', 'dir': str(self.root),
                    'result': {'source_sha256': 'source-hash', 'document_id': 'sample',
                               'bom': {'components': [{'part_number': 'A', 'quantity': 1}]}}}
        for key, value in [('DATA_DIR', str(self.root)), ('REVIEWLOG_PATH', str(self.root / 'log.json')),
                           ('_jobs', {'j': self.job})]:
            context = patch.object(webapp, key, value)
            context.start()
            self.addCleanup(context.stop)
        self.handler = object.__new__(webapp.Handler)
        self.responses = []
        self.handler._json = lambda data, *a, **k: self.responses.append(data)

    def save(self, quantity, part='A'):
        self.handler._read_json_body = lambda: {'job_id': 'j', 'document_id': 'sample',
            'components': [{'part_number': part, 'quantity': quantity}]}
        self.handler._api_bom_save()

    def test_fractional_and_nonfinite_quantities_rejected_without_writes(self):
        for quantity in (1.5, True, 'abc', float('inf'), float('nan')):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                self.save(quantity)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.job['result']['bom']['components'][0]['quantity'], 1)

    def test_valid_quantities_match_export_conversion(self):
        for quantity in (0, 4, None):
            self.save(quantity)
            bom = self.job['result']['bom']
            self.assertEqual(bom['components'][0]['quantity'], webapp._bom_document_from(bom).components[0].quantity)
            self.assertEqual(bom['summary']['total_quantity'], quantity or 0)

    def test_each_edit_is_recoverable(self):
        self.save(2)
        self.save(3)
        records = json.loads((self.root / 'log.json').read_text(encoding='utf-8'))
        self.assertEqual([(r['before'][0]['quantity'], r['after'][0]['quantity']) for r in records], [(1, 2), (2, 3)])
        for record in records:
            snapshot = json.loads(Path(record['snapshot']).read_text(encoding='utf-8'))
            self.assertEqual(snapshot['before'], record['before'])
            self.assertEqual(snapshot['after'], record['after'])
            self.assertEqual(snapshot['source_sha256'], 'source-hash')
        self.assertNotEqual(records[0]['snapshot'], records[1]['snapshot'])

    def test_failed_log_write_rolls_back_edit_and_snapshot(self):
        self.save(2)
        before = {p: p.read_bytes() for p in self.root.rglob('*.json')}
        atomic = webapp._atomic_json
        def fail_log(path, value):
            if str(path) == str(self.root / 'log.json'):
                raise OSError('simulated audit disk failure')
            return atomic(path, value)
        with patch.object(webapp, '_atomic_json', side_effect=fail_log):
            with self.assertRaises(OSError):
                self.save(3)
        self.assertEqual(self.job['result']['bom']['components'][0]['quantity'], 2)
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob('*.json')}, before)

    def test_corrupt_audit_blocks_edit_without_overwrite(self):
        self.save(2)
        (self.root / 'log.json').write_text('{broken', encoding='utf-8')
        before = {p: p.read_bytes() for p in self.root.rglob('*.json')}
        with self.assertRaises(ValueError):
            self.save(3)
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob('*.json')}, before)

    def test_stale_assembly_rejected_current_revision_accepted(self):
        tree = {'nodes': [{'id': 'n', 'parent_id': None, 'component_index': 0,
                           'source_page': 1, 'evidence': 'A label'}]}
        self.save(1, 'B')
        revision = self.responses[-1]['bom']['revision']
        self.assertEqual(self.responses[-1]['bom']['assembly']['nodes'], [])
        body = {'job_id': 'j', 'reviewer': 'tester', 'assembly': tree, 'bom_revision': 0}
        self.handler._read_json_body = lambda: body
        with self.assertRaisesRegex(ValueError, '版本已变化'):
            self.handler._api_assembly_save()
        body['bom_revision'] = revision
        tree['nodes'][0]['evidence'] = 'B label, manually rechecked'
        self.handler._api_assembly_save()
        self.assertEqual(self.responses[-1]['assembly']['status'], 'reviewed')

    def test_mixed_pdf_and_vector_changes_cannot_report_no_change(self):
        for kind in ('image', 'vector'):
            with self.subTest(kind=kind):
                target = self.root / (kind + '.pdf')
                with fitz.open() as doc:
                    page = doc.new_page()
                    page.insert_text((30, 30), 'Unchanged title')
                    if kind == 'image':
                        buffer = io.BytesIO()
                        Image.new('RGB', (20, 20), 'black').save(buffer, format='PNG')
                        page.insert_image(fitz.Rect(40, 50, 100, 100), stream=buffer.getvalue())
                    else:
                        page.draw_line((40, 50), (100, 100))
                    doc.save(target)
                with self.assertRaisesRegex(ValueError, '比较不完整'):
                    extract_text(str(target))

    def test_text_pdf_comparison_still_works(self):
        sources = []
        for number in (4, 8):
            target = self.root / ('text%d.pdf' % number)
            with fitz.open() as doc:
                doc.new_page().insert_text((30, 30), 'Quantity: %d' % number)
                doc.save(target)
            sources.append(extract_text(str(target))['paragraphs'])
        self.assertEqual(len(align_and_diff(*sources)), 1)


if __name__ == '__main__':
    unittest.main()
