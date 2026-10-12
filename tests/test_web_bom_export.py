"""Exercise the actual HTTP export handler without starting a socket server."""
import csv
import io
import unittest
from unittest.mock import Mock

from engine_bom.webapp import Handler


class WebBomExportTests(unittest.TestCase):
    def test_csv_export_has_public_headers_and_preserves_quoted_values(self):
        handler = Handler.__new__(Handler)
        handler.path = '/api/export/bom/test?fmt=csv'
        handler._job_result = Mock(return_value={
            'document_id': '图纸测试',
            'bom': {'components': [{'item_no': '1', 'name_zh': '盖,输入端',
                                    'quantity': 2, 'remark': '第一行\n第二行'}]},
        })
        handler._send = Mock()
        handler._api_export_bom('test')
        code, body, content_type, filename = handler._send.call_args.args
        self.assertEqual(code, 200)
        self.assertEqual(content_type, 'text/csv; charset=utf-8')
        self.assertEqual(filename, '图纸测试.csv')
        self.assertTrue(body.startswith(b'\xef\xbb\xbf'))
        rows = list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))))
        self.assertEqual(len(rows), 1)
        self.assertNotIn('置信度', rows[0])
        self.assertEqual(rows[0]['名称(中文)'], '盖,输入端')
        self.assertEqual(rows[0]['备注'], '第一行\n第二行')
        self.assertEqual(rows[0]['数量'], '2')


if __name__ == '__main__':
    unittest.main()
