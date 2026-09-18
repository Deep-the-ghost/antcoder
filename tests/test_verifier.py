import unittest
import tempfile
import shutil
from pathlib import Path

from antcoder.verifier import Verifier, Diagnostic


class TestVerifierMultiRuntime(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_valid_javascript_passes(self):
        js_file = self.test_dir / "valid.js"
        js_file.write_text("""
        class Player {
            constructor(x, y) {
                this.x = x;
                this.y = y;
            }
            move() {
                this.x += 1;
            }
        }
        """)
        verifier = Verifier(self.test_dir, build_cmd=["true"])
        success, diags, raw = verifier.run_compiler(target_file="valid.js")
        self.assertTrue(success, f"Expected valid JS to pass, but got diags: {diags}")
        self.assertEqual(len(diags), 0)

    def test_invalid_javascript_with_typescript_syntax_fails(self):
        # Simulates the exact failure mode from the Mario game
        bad_js = self.test_dir / "bad.js"
        bad_js.write_text("""
        class Game {
            private player: Player;
            constructor() {
                this.player = null;
            }
        }
        """)
        verifier = Verifier(self.test_dir, build_cmd=["true"])
        success, diags, raw = verifier.run_compiler(target_file="bad.js")
        self.assertFalse(success, "Expected invalid JS with TS syntax to fail verification")
        self.assertGreater(len(diags), 0)
        self.assertEqual(diags[0].code, "JS_SYNTAX")
        self.assertEqual(diags[0].file, "bad.js")
        self.assertIn("player", diags[0].message)

    def test_invalid_python_syntax_fails(self):
        bad_py = self.test_dir / "bad.py"
        bad_py.write_text("def foo( missing_paren:\n    pass\n")
        verifier = Verifier(self.test_dir, build_cmd=["true"])
        success, diags, raw = verifier.run_compiler(target_file="bad.py")
        self.assertFalse(success, "Expected invalid Python syntax to fail verification")
        self.assertGreater(len(diags), 0)
        self.assertEqual(diags[0].code, "PY_SYNTAX")
        self.assertEqual(diags[0].file, "bad.py")

    def test_extract_context(self):
        sample = self.test_dir / "sample.js"
        sample.write_text("line 1\nline 2\nline 3\nline 4\nline 5\n")
        verifier = Verifier(self.test_dir, build_cmd=["true"])
        ctx = verifier.extract_context("sample.js", line_no=3, window=1)
        self.assertIn("line 3", ctx)
        self.assertIn("   3: ", ctx)


if __name__ == "__main__":
    unittest.main()
