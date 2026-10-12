"""Isolated code-review reproductions; no API calls or production data writes."""
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
from PIL import Image, ImageDraw
from engine_bom import webapp
from engine_bom.changedetect import extract_text, align_and_diff


def main():
    findings = {}
    with tempfile.TemporaryDirectory() as folder:
        pdfs = []
        for quantity in (4, 8):
            image = Image.new('RGB', (600, 200), 'white')
            ImageDraw.Draw(image).text((30, 70), 'BOLT QUANTITY: %d' % quantity, fill='black', font_size=32)
            stream = io.BytesIO()
            image.save(stream, format='PNG')
            path = os.path.join(folder, 'v%d.pdf' % quantity)
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((40, 40), 'Drawing revision comparison')
                page.insert_image(fitz.Rect(40, 100, 550, 270), stream=stream.getvalue())
                doc.save(path)
            pdfs.append(path)
        before, after = [extract_text(p) for p in pdfs]
        findings['mixed_pdf_changed_image'] = {
            'expected': 'detect change or explicitly reject incomplete comparison',
            'actual_change_count': len(align_and_diff(before['paragraphs'], after['paragraphs'])),
            'extracted_paragraphs': before['paragraphs'],
        }
        job = {'kind': 'bom', 'status': 'done', 'dir': folder,
               'result': {'document_id': 'audit', 'bom': {'components': [{'part_number': 'A', 'quantity': 1}]}}}
        handler = object.__new__(webapp.Handler)
        responses = []
        handler._json = lambda data, *a, **k: responses.append(data)
        with patch.object(webapp, '_jobs', {'j': job}), patch.object(webapp, 'DATA_DIR', folder), patch.object(webapp, 'REVIEWLOG_PATH', os.path.join(folder, 'log.json')):
            for quantity in (2, 3):
                handler._read_json_body = lambda q=quantity: {'job_id': 'j', 'document_id': 'audit', 'components': [{'part_number': 'A', 'quantity': q}]}
                handler._api_bom_save()
            logs = json.loads(Path(folder, 'log.json').read_text(encoding='utf-8'))
            findings['bom_edit_audit'] = {'expected': 'recover quantities 1 -> 2 -> 3', 'actual_logs': logs, 'saved_quantity': json.loads(Path(folder, 'reviewed', 'audit.json').read_text(encoding='utf-8'))['components'][0]['quantity']}
            handler._read_json_body = lambda: {'job_id': 'j', 'document_id': 'audit', 'components': [{'part_number': 'A', 'quantity': 1.5}]}
            handler._api_bom_save()
            bom = job['result']['bom']
            findings['invalid_quantity_save'] = {'expected': 'reject invalid integer or consistently retain flagged value', 'save_ok': responses[-1]['ok'], 'json_quantity': bom['components'][0]['quantity'], 'csv_xlsx_quantity': webapp._bom_document_from(bom).components[0].quantity, 'summary': bom['summary']}
        tree = {'nodes': [{'id': 'n', 'component_index': 0, 'parent_id': None, 'source_page': 1, 'evidence': 'original A label'}]}
        job['result']['bom']['assembly'] = tree
        with patch.object(webapp, '_jobs', {'j': job}), patch.object(webapp, 'DATA_DIR', folder), patch.object(webapp, 'REVIEWLOG_PATH', os.path.join(folder, 'log.json')):
            handler._read_json_body = lambda: {'job_id': 'j', 'document_id': 'audit', 'components': [{'part_number': 'B', 'quantity': 1}]}
            handler._api_bom_save()
            invalidated = job['result']['bom']['assembly']['inference_status']
            handler._read_json_body = lambda: {'job_id': 'j', 'reviewer': 'tester', 'assembly': tree}
            handler._api_assembly_save()
            findings['stale_assembly_resubmit'] = {'expected': 'stale UI tree must be invalidated/refreshed after BOM edit', 'before_resubmit': invalidated, 'after_resubmit': job['result']['bom']['assembly']['status'], 'component_now': job['result']['bom']['components'][0]['part_number'], 'old_evidence': job['result']['bom']['assembly']['nodes'][0]['evidence']}
    print(json.dumps(findings, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
