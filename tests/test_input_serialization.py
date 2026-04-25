import unittest
from datetime import datetime
from pathlib import Path

from prism import _serialize_inputs


class TestSerializeInputs(unittest.TestCase):
    def test_boolean_preserved(self):
        out = _serialize_inputs({"flag": True})
        self.assertIs(out["flag"], True)
        self.assertIsInstance(out["flag"], bool)

    def test_integer_preserved(self):
        out = _serialize_inputs({"count": 42})
        self.assertEqual(out["count"], 42)
        self.assertIsInstance(out["count"], int)
        self.assertNotIsInstance(out["count"], bool)

    def test_float_preserved(self):
        out = _serialize_inputs({"ratio": 0.5})
        self.assertEqual(out["ratio"], 0.5)
        self.assertIsInstance(out["ratio"], float)

    def test_string_preserved(self):
        out = _serialize_inputs({"name": "alice"})
        self.assertEqual(out["name"], "alice")
        self.assertIsInstance(out["name"], str)

    def test_list_preserved_with_element_types(self):
        out = _serialize_inputs({"items": [1, "two", True]})
        self.assertEqual(out["items"], [1, "two", True])
        self.assertIsInstance(out["items"][0], int)
        self.assertIsInstance(out["items"][1], str)
        self.assertIs(out["items"][2], True)

    def test_nested_dict_preserved(self):
        out = _serialize_inputs({"meta": {"version": 2}})
        self.assertEqual(out["meta"], {"version": 2})
        self.assertIsInstance(out["meta"], dict)
        self.assertIsInstance(out["meta"]["version"], int)

    def test_none_preserved(self):
        out = _serialize_inputs({"opt": None})
        self.assertIn("opt", out)
        self.assertIsNone(out["opt"])

    def test_datetime_stringified(self):
        out = _serialize_inputs({"when": datetime(2026, 4, 25, 10, 30)})
        self.assertIsInstance(out["when"], str)
        self.assertTrue(out["when"])

    def test_pathlib_path_stringified(self):
        out = _serialize_inputs({"path": Path("/tmp/x")})
        self.assertIsInstance(out["path"], str)
        self.assertIn("/tmp/x", out["path"])

    def test_empty_dict(self):
        self.assertEqual(_serialize_inputs({}), {})


if __name__ == "__main__":
    unittest.main()
