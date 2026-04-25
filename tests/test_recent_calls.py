import unittest
from datetime import datetime
from pathlib import Path

from prism import (
    _input_preview,
    _record_recent_call,
    _recent_calls,
    _tool_docs,
    watch,
)


class TestRecentCallBuffer(unittest.TestCase):
    def setUp(self):
        _recent_calls.clear()

    def test_buffer_bounded_to_five_entries(self):
        for i in range(7):
            _record_recent_call(f"tool_{i}", {"i": i}, "success", float(i), "2026-04-25T00:00:00")
        self.assertEqual(len(_recent_calls), 5)

    def test_buffer_preserves_insertion_order_and_keeps_last_five(self):
        for i in range(7):
            _record_recent_call(f"tool_{i}", {"i": i}, "success", float(i), "2026-04-25T00:00:00")
        names = [e["tool_name"] for e in _recent_calls]
        self.assertEqual(names, ["tool_2", "tool_3", "tool_4", "tool_5", "tool_6"])

    def test_buffer_records_all_three_statuses(self):
        _record_recent_call("a", {"x": 1}, "success",  10.0, "2026-04-25T00:00:00")
        _record_recent_call("b", {"x": 2}, "failure",  20.0, "2026-04-25T00:00:01")
        _record_recent_call("c", {"x": 3}, "rejected",  0.0, "2026-04-25T00:00:02")
        statuses = [e["status"] for e in _recent_calls]
        self.assertEqual(statuses, ["success", "failure", "rejected"])

    def test_entry_shape(self):
        _record_recent_call("foo", {"k": "v"}, "success", 12.5, "2026-04-25T00:00:00")
        e = _recent_calls[0]
        self.assertEqual(set(e.keys()), {"tool_name", "inputs_preview", "status", "duration_ms", "timestamp_end"})
        self.assertEqual(e["tool_name"], "foo")
        self.assertEqual(e["status"], "success")
        self.assertEqual(e["duration_ms"], 12.5)


class TestInputPreview(unittest.TestCase):
    def test_short_input_renders_as_compact_json(self):
        out = _input_preview({"q": "hi"})
        self.assertEqual(out, '{"q": "hi"}')
        self.assertNotIn("...", out)

    def test_long_input_truncated_with_ellipsis(self):
        out = _input_preview({"content": "x" * 500})
        self.assertLessEqual(len(out), 63)
        self.assertTrue(out.endswith("..."))

    def test_non_serializable_value_is_coerced(self):
        out = _input_preview({"when": datetime(2026, 4, 25, 10, 30)})
        self.assertIsInstance(out, str)
        self.assertTrue(out)

    def test_pathlib_path_is_coerced(self):
        out = _input_preview({"path": Path("/tmp/x")})
        self.assertIsInstance(out, str)
        self.assertIn("/tmp/x", out)


class TestDocstringCapture(unittest.TestCase):
    def test_function_with_docstring_is_captured(self):
        @watch
        def my_tool_with_docs(x):
            """Reads X and returns Y."""
            return x

        self.assertIn("my_tool_with_docs", _tool_docs)
        self.assertEqual(_tool_docs["my_tool_with_docs"], "Reads X and returns Y.")

    def test_function_without_docstring_is_not_added(self):
        @watch
        def my_tool_no_docs(x):
            return x

        self.assertNotIn("my_tool_no_docs", _tool_docs)

    def test_docstring_is_stripped(self):
        @watch
        def my_tool_padded_docs(x):
            """
            Padded docstring with leading and trailing whitespace.
            """
            return x

        self.assertEqual(
            _tool_docs["my_tool_padded_docs"],
            "Padded docstring with leading and trailing whitespace.",
        )


if __name__ == "__main__":
    unittest.main()
