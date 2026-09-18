import unittest
import tempfile
import shutil
from pathlib import Path

from antcoder.engine import ScaffoldingEngine
from antcoder.verifier import Diagnostic


class DummyModelClient:
    def query(self, messages, model_type="builder"):
        return "{}"


class TestIncrementalEngine(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        # Init git repo
        import subprocess
        subprocess.run(["git", "init"], cwd=self.test_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.test_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=self.test_dir, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=self.test_dir, capture_output=True)
        self.engine = ScaffoldingEngine(self.test_dir, model_client=DummyModelClient())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_scan_repository_identifies_files_and_classes(self):
        (self.test_dir / "player.js").write_text("class Player { constructor() { this.x = 0; } }")
        (self.test_dir / "index.html").write_text("<!DOCTYPE html><html><body></body></html>")

        summary = self.engine.scan_repository()
        self.assertIn("existing file(s)", summary)
        self.assertIn("player.js", summary)
        self.assertIn("classes: Player", summary)
        self.assertIn("index.html", summary)
        self.assertIn("HTML entrypoint", summary)

    def test_per_task_diagnostic_scoping(self):
        target_file = "bird.js"
        target_name = Path(target_file).name
        dag_files = {"bird.js", "pipe.js"}

        diagnostics = [
            Diagnostic("bird.js", 10, 1, "JS_SYNTAX", "SyntaxError in bird", "raw1"),
            Diagnostic("pipe.js", 25, 1, "JS_SYNTAX", "SyntaxError in pipe", "raw2"),
            Diagnostic("other.js", 5, 1, "TS2307", "Cannot find module bird", "raw3"),
        ]

        actionable = [
            d for d in diagnostics
            if (d.file == target_file or Path(d.file).name == target_name)
            and not (d.code == "TS2307" and any(Path(df).stem in d.message for df in dag_files))
        ]

        # Only bird.js diagnostic should be actionable for bird.js task
        self.assertEqual(len(actionable), 1)
        self.assertEqual(actionable[0].file, "bird.js")


if __name__ == "__main__":
    unittest.main()
