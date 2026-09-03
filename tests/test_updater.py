"""自动更新纯逻辑测试。"""

from __future__ import annotations

import unittest

from rmqueue import updater


class TestParseVersion(unittest.TestCase):
    def test_plain_and_v_prefix(self) -> None:
        self.assertEqual(updater.parse_version("0.1.1"), (0, 1, 1))
        self.assertEqual(updater.parse_version("v0.2.0"), (0, 2, 0))
        self.assertEqual(updater.parse_version("V0.1.0"), (0, 1, 0))

    def test_suffix_ignored(self) -> None:
        self.assertEqual(updater.parse_version("v0.2.0-beta1"), (0, 2, 0))

    def test_invalid_raises(self) -> None:
        with self.assertRaises(ValueError):
            updater.parse_version("latest")


class TestIsNewer(unittest.TestCase):
    def test_newer(self) -> None:
        self.assertTrue(updater.is_newer("v0.2.0", "0.1.1"))
        self.assertTrue(updater.is_newer("v0.1.10", "0.1.9"))

    def test_not_newer(self) -> None:
        self.assertFalse(updater.is_newer("v0.1.1", "0.1.1"))
        self.assertFalse(updater.is_newer("v0.1.0", "0.1.1"))


class TestFindSetupAsset(unittest.TestCase):
    def test_find_setup_asset(self) -> None:
        release = {"assets": [
            {"name": "RenderMonitorQueue-Setup-0.2.0.exe",
             "browser_download_url": "https://example/setup.exe"},
            {"name": "README.md"},
        ]}
        asset = updater.find_setup_asset(release)
        self.assertIsNotNone(asset)
        self.assertEqual(asset["name"], "RenderMonitorQueue-Setup-0.2.0.exe")

    def test_no_asset(self) -> None:
        self.assertIsNone(updater.find_setup_asset({"assets": []}))


class TestCheckLatestReleaseParsing(unittest.TestCase):
    """用 stub 网络层验证 check_latest_release 的组装逻辑。"""

    def test_update_available(self) -> None:
        original = updater.fetch_latest_release
        updater.fetch_latest_release = lambda *a, **kw: {
            "tag_name": "v0.2.0",
            "html_url": "https://github.com/x/releases/tag/v0.2.0",
            "published_at": "2025-01-01T00:00:00Z",
            "assets": [{"name": "RenderMonitorQueue-Setup-0.2.0.exe"}],
        }
        try:
            result = updater.check_latest_release("0.1.1")
        finally:
            updater.fetch_latest_release = original
        self.assertTrue(result["update_available"])
        self.assertEqual(result["latest_version"], "0.2.0")
        self.assertIsNotNone(result["asset"])

    def test_no_update(self) -> None:
        original = updater.fetch_latest_release
        updater.fetch_latest_release = lambda *a, **kw: {
            "tag_name": "v0.1.1",
            "html_url": "https://github.com/x/releases/tag/v0.1.1",
            "assets": [],
        }
        try:
            result = updater.check_latest_release("0.1.1")
        finally:
            updater.fetch_latest_release = original
        self.assertFalse(result["update_available"])


if __name__ == "__main__":
    unittest.main()
