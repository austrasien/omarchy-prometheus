import tempfile
import unittest
from pathlib import Path

from prometheus.apps import AppNames, build_index


class AppsTest(unittest.TestCase):
    def test_index_and_names(self):
        with tempfile.TemporaryDirectory() as d:
            apps = Path(d) / "applications"
            apps.mkdir()
            (apps / "org.gnome.Nautilus.desktop").write_text("[Desktop Entry]\nName=Fichiers\n[Desktop Action x]\nName=Autre\n")
            (apps / "code-oss.desktop").write_text("[Desktop Entry]\nName=Code - OSS\nStartupWMClass=Code\n")
            (apps / "YouTube.desktop").write_text("[Desktop Entry]\nName=YouTube\nExec=omarchy-launch-webapp https://www.youtube.com/\n")
            n = AppNames(build_index([Path(d)]))
        self.assertEqual(n.name("org.gnome.Nautilus"), "Fichiers")
        self.assertEqual(n.name("nautilus"), "Fichiers")
        self.assertEqual(n.name("Code"), "Code - OSS")
        self.assertEqual(n.name("brave-youtube.com__-Default"), "YouTube")
        self.assertEqual(n.name("chromium-docs.example.org_doc_-Default"), "docs.example.org")
        self.assertEqual(n.name("some-tool"), "Some Tool")
        self.assertEqual(n.name(None, "/usr/bin/foot"), "Foot")
        self.assertIsNone(n.name(None))


if __name__ == "__main__":
    unittest.main()
