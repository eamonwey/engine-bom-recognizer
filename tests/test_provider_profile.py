import io
import json
import unittest
import urllib.error
from unittest.mock import patch
from engine_bom.providers.openai_compat import OpenAICompatVisionProvider


class ProviderProfileTests(unittest.TestCase):
    def test_alphabetic_item_label_preserved_without_losing_table(self):
        from engine_bom.agent_loop import validate_bom_response
        components, errors = validate_bom_response(json.dumps({"components":[{"item_no":"a", "part_number":"1025G1050-5", "quantity":2}]}))
        self.assertFalse(errors)
        self.assertIsNone(components[0].item_no)
        self.assertEqual(components[0].quantity, 2)
        self.assertIn("'a'", components[0].remark)

    def test_explicit_direct_profile_and_usage(self):
        provider = OpenAICompatVisionProvider({"base_url":"http://test.invalid/v1", "model":"qwen3.8-max", "api_key":"test-only", "enable_thinking":False})
        captured = []
        def request(req, **kwargs):
            captured.append(json.loads(req.data.decode("utf-8")))
            return io.BytesIO(json.dumps({"choices":[{"message":{"content":"{}"}}],"usage":{"total_tokens":12}}).encode())
        with patch("urllib.request.urlopen", side_effect=request):
            response = provider.analyze([], "test")
        self.assertIs(captured[0]["enable_thinking"], False)
        self.assertEqual(response.usage, {"total_tokens":12})
        self.assertNotIn("test-only", json.dumps(provider.describe()))

    def test_generic_endpoint_omits_vendor_option(self):
        provider = OpenAICompatVisionProvider({"base_url":"http://test.invalid/v1", "model":"local", "api_key":"test-only", "enable_thinking":False})
        with patch.object(provider, "_post_chat", return_value="{}") as send:
            provider.analyze([], "test")
        self.assertNotIn("enable_thinking", send.call_args[0][0])

    def test_exhausted_free_quota_is_not_retried(self):
        from engine_bom.providers.base import ProviderConfigError
        provider = OpenAICompatVisionProvider({"base_url":"http://test.invalid/v1", "model":"qwen3.8-max", "api_key":"test-only", "retries":2})
        error = urllib.error.HTTPError("http://test.invalid",403,"Forbidden",{},io.BytesIO(b'{"code":"AllocationQuota.FreeTierOnly"}'))
        with patch("urllib.request.urlopen",side_effect=error) as send:
            with self.assertRaisesRegex(ProviderConfigError,"AllocationQuota.FreeTierOnly"):
                provider.analyze([],"test")
        self.assertEqual(send.call_count,1)


if __name__ == "__main__":
    unittest.main()
