# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine_bom.parsing import extract_json_payload, response_to_components


class TestExtractJson(unittest.TestCase):
    def test_plain_json(self):
        payload, warns = extract_json_payload('{"components": []}')
        self.assertEqual(payload, {"components": []})
        self.assertEqual(warns, [])

    def test_fenced_json_with_prose(self):
        text = '识别结果如下：\n```json\n{"components": [{"name_zh": "活塞"}]}\n```\n以上。'
        payload, _ = extract_json_payload(text)
        self.assertEqual(payload["components"][0]["name_zh"], "活塞")

    def test_trailing_comma_repair(self):
        text = '{"components": [{"name_zh": "活塞", "quantity": 4,},],}'
        payload, warns = extract_json_payload(text)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["components"][0]["quantity"], 4)

    def test_bare_list(self):
        payload, _ = extract_json_payload('[{"name_zh": "活塞"}]')
        self.assertIsInstance(payload, list)

    def test_garbage(self):
        payload, warns = extract_json_payload("抱歉，我无法识别该图像。")
        self.assertIsNone(payload)
        self.assertTrue(warns)

    def test_empty(self):
        payload, warns = extract_json_payload("   ")
        self.assertIsNone(payload)
        self.assertTrue(warns)


class TestResponseToComponents(unittest.TestCase):
    def test_end_to_end(self):
        raw = '```json\n{"components": [{"序号": 1, "名称": "曲轴", "数量": "1台"}]}\n```'
        comps, warns = response_to_components(raw)
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].name_zh, "曲轴")
        self.assertEqual(comps[0].quantity, 1)
        self.assertTrue(any("额外文本" in w for w in warns))

    def test_dict_without_components(self):
        comps, warns = response_to_components('{"foo": 1}')
        self.assertEqual(comps, [])
        self.assertTrue(warns)


if __name__ == "__main__":
    unittest.main()
