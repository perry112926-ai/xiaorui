import unittest
from types import SimpleNamespace
from app.mcp_payload import extract_payload,PayloadError
from app.mcd import _payload,McdRejectedError

def result(texts=(),structured=None,error=False):
    return SimpleNamespace(isError=error,structuredContent=structured,content=[SimpleNamespace(type='text',text=t) for t in texts])

class McpPayloadTests(unittest.TestCase):
    def test_structured_content_is_authoritative(self):
        self.assertEqual(extract_payload(result(['{"bad":true}'],{'data':'actual'})),{'data':'actual'})
    def test_ambiguous_or_missing_payload_is_rejected(self):
        for response in [result(['unparseable']),result(['{}','{}'])]:
            with self.assertRaises(PayloadError):extract_payload(response)
    def test_provider_envelopes_keep_distinct_business_success_rules(self):
        self.assertEqual(_payload(result(['tool result: {"data":{"name":"公开餐品"},"success":true}'])),{'name':'公开餐品'})
        with self.assertRaises(McdRejectedError):_payload(result(structured={'success':False,'data':{}}))
        with self.assertRaises(RuntimeError):_payload(result(structured={'success':True}))
    def test_two_embedded_envelopes_never_select_arbitrarily(self):
        with self.assertRaises(RuntimeError):_payload(result(['{"success":true,"data":{}} {"success":true,"data":{}}']))
