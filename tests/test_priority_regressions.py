# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from io import BytesIO
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine_bom.docextract import parse_document
from engine_bom.inspect_rules import (check_balloon_consistency, check_bom_table,
                                      check_dimensions, check_titleblock, run_all_checks)
from engine_bom import webapp
from engine_bom.webapp import Handler, RequestTooLarge, _API_TOKEN, _safe_review_path


class TestInspectionRegressions(unittest.TestCase):
    def test_float_balloon_numbers_are_checked(self):
        issues = check_balloon_consistency([1.0, 2.0, 3.0],
                                           [{"item_no": 1}, {"item_no": 2}])
        self.assertTrue(any("明细栏缺失" in issue["message"] for issue in issues))

    def test_standard_parts_with_different_specs_are_not_duplicates(self):
        issues = check_bom_table([
            {"item_no": 1, "part_number": "GB/T 5782", "specification": "M8×30", "quantity": 1},
            {"item_no": 2, "part_number": "GB/T 5782", "specification": "M10×40", "quantity": 1},
        ])
        self.assertFalse(any("图号重复" in issue["message"] for issue in issues))

    def test_out_of_order_complete_numbers_are_not_missing(self):
        issues = check_bom_table([
            {"item_no": 2, "part_number": "P2", "quantity": 1},
            {"item_no": 1, "part_number": "P1", "quantity": 1},
            {"item_no": 3, "part_number": "P3", "quantity": 1},
        ])
        self.assertFalse(any("序号不连续" in issue["message"] for issue in issues))

    def test_non_numeric_printed_quantity_is_preserved_without_missing_error(self):
        issues = check_bom_table([
            {"item_no": 1, "part_number": "P1", "quantity": None,
             "remark": "原数量 AR（按需）"},
        ])
        self.assertFalse(any("数量缺失" in issue["message"] for issue in issues))

    def test_common_material_names_are_accepted(self):
        required = {"drawing_name": "x", "drawing_no": "x", "designer": "x", "date": "x",
                    "material_applicable": True}
        for material in ["45钢", "6061-T6", "7075-T651", "不锈钢304", "铝合金",
                         "45#", "Inconel718", "HT250 / 4032 铝合金", "HT250-GB/T9439"]:
            issues = check_titleblock(dict(required, material=material))
            self.assertFalse(any("材料填写疑似不规范" in issue["message"] for issue in issues), material)

    def test_unknown_material_applicability_does_not_assert_missing_material(self):
        issues = check_titleblock({"drawing_name": "x", "drawing_no": "x", "designer": "x",
                                   "date": "x", "drawing_type": "unknown",
                                   "material_applicable": None, "material": ""})
        self.assertFalse(any(issue["err_id"] == "ERR-06" for issue in issues))

    def test_generic_dimension_labels_do_not_link_unrelated_features(self):
        issues = check_dimensions([
            {"tag": "孔径", "value": "10", "view": "A"},
            {"tag": "孔径", "value": "20", "view": "B"},
        ])
        self.assertEqual(issues, [])

    def test_dimension_normalization_handles_thousands_and_uppercase_units(self):
        self.assertEqual(check_dimensions([
            {"tag": "L", "value": "1,200"}, {"tag": "L", "value": "1200"},
        ]), [])

    def test_balloon_check_can_be_disabled_after_row_renumbering(self):
        issues = run_all_checks(components=[{"item_no": 1}], balloons=[9],
                                check_balloons=False)
        self.assertFalse(any("引出序号" in issue["message"] for issue in issues))
        self.assertEqual(check_dimensions([
            {"tag": "D", "value": "10MM"}, {"tag": "D", "value": "10mm"},
        ]), [])


class TestDocxRegression(unittest.TestCase):
    def test_table_cell_text_is_not_duplicated_as_paragraph(self):
        xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:tbl><w:tr><w:tc><w:p><w:r><w:t>CELL</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body>
</w:document>'''
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", xml)
            parsed = parse_document(path)
            self.assertEqual(parsed["text"].splitlines().count("CELL"), 1)
        finally:
            os.unlink(path)


class TestWebSecurityRegressions(unittest.TestCase):
    def test_review_path_cannot_escape_parent(self):
        with tempfile.TemporaryDirectory() as parent:
            safe = _safe_review_path(parent, "web_job-01")
            self.assertEqual(os.path.dirname(safe), os.path.realpath(parent))
            for malicious in ("../settings", "..\\settings", "C:\\temp\\owned", "/tmp/owned"):
                with self.subTest(malicious=malicious):
                    with self.assertRaises(ValueError):
                        _safe_review_path(parent, malicious)

    def test_web_responses_do_not_enable_cross_origin_and_post_requires_token(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            conn.request("GET", "/")
            response = conn.getresponse()
            html = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIsNone(response.getheader("Access-Control-Allow-Origin"))
            self.assertNotIn("__ENGINE_BOM_API_TOKEN__", html)

            conn.request("POST", "/api/nope", body=b"")
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 403)

            conn.request("POST", "/api/nope", body=b"",
                         headers={"X-API-Token": _API_TOKEN})
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 404)
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_frontend_escapes_model_and_document_cells(self):
        app_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "app.js")
        with open(app_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('esc(model)', source)
        self.assertIn('esc(row[k] === undefined', source)

    def test_multipart_parser_and_request_limit(self):
        boundary = "----engine-bom-test"
        body = ("--%s\r\nContent-Disposition: form-data; name=\"provider\"\r\n\r\nmock\r\n"
                "--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.txt\"\r\n"
                "Content-Type: text/plain\r\n\r\nhello\r\n--%s--\r\n"
                % (boundary, boundary, boundary)).encode("utf-8")
        handler = object.__new__(Handler)
        handler.headers = {"Content-Type": "multipart/form-data; boundary=%s" % boundary,
                           "Content-Length": str(len(body))}
        handler.rfile = BytesIO(body)
        form = handler._form()
        self.assertEqual(form.getvalue("provider"), "mock")
        self.assertEqual(form["file"].filename, "a.txt")
        self.assertEqual(form["file"].file.read(), b"hello")

        old_limit = webapp.MAX_REQUEST_BYTES
        try:
            webapp.MAX_REQUEST_BYTES = len(body) - 1
            handler.rfile = BytesIO(body)
            with self.assertRaises(RequestTooLarge):
                handler._form()
        finally:
            webapp.MAX_REQUEST_BYTES = old_limit

    def test_completed_jobs_are_expired_but_running_jobs_survive(self):
        old_jobs = dict(webapp._jobs)
        old_ttl = webapp.JOB_TTL_SECONDS
        try:
            webapp._jobs.clear()
            webapp.JOB_TTL_SECONDS = 10
            with tempfile.TemporaryDirectory() as parent:
                old_dir = os.path.join(parent, "old")
                running_dir = os.path.join(parent, "running")
                os.makedirs(old_dir)
                os.makedirs(running_dir)
                webapp._jobs.update({
                    "old": {"id": "old", "status": "done", "created_ts": 1, "dir": old_dir},
                    "running": {"id": "running", "status": "running", "created_ts": 1,
                                "dir": running_dir},
                })
                webapp._cleanup_jobs(now=100)
                self.assertNotIn("old", webapp._jobs)
                self.assertFalse(os.path.exists(old_dir))
                self.assertIn("running", webapp._jobs)
                self.assertTrue(os.path.isdir(running_dir))
        finally:
            webapp._jobs.clear()
            webapp._jobs.update(old_jobs)
            webapp.JOB_TTL_SECONDS = old_ttl


if __name__ == "__main__":
    unittest.main()
