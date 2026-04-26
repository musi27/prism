import os
import unittest
from unittest import mock

from prism import _get_ui_url


class TestGetUiUrl(unittest.TestCase):
    def setUp(self):
        self._patcher = mock.patch.dict(os.environ, {}, clear=False)
        self._patcher.start()
        os.environ.pop("PRISM_UI_HOST", None)
        os.environ.pop("PRISM_UI_PORT", None)

    def tearDown(self):
        self._patcher.stop()

    def test_default_when_neither_env_var_set(self):
        self.assertEqual(_get_ui_url(), "http://localhost:4242")

    def test_uses_host_env_var(self):
        os.environ["PRISM_UI_HOST"] = "192.168.1.5"
        self.assertEqual(_get_ui_url(), "http://192.168.1.5:4242")

    def test_uses_port_env_var(self):
        os.environ["PRISM_UI_PORT"] = "5050"
        self.assertEqual(_get_ui_url(), "http://localhost:5050")

    def test_uses_both_when_both_set(self):
        os.environ["PRISM_UI_HOST"] = "agent.internal"
        os.environ["PRISM_UI_PORT"] = "7000"
        self.assertEqual(_get_ui_url(), "http://agent.internal:7000")

    def test_empty_string_falls_back_to_default(self):
        os.environ["PRISM_UI_HOST"] = ""
        os.environ["PRISM_UI_PORT"] = ""
        self.assertEqual(_get_ui_url(), "http://localhost:4242")


if __name__ == "__main__":
    unittest.main()
