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

    def test_detects_empty_comment_stub(self):
        # Simulates the hollow physics.js stub from the Mario game
        stub_js = self.test_dir / "physics.js"
        stub_js.write_text("""
        class Physics {
            applyGravity() {
                // Gravity logic
            }
            applyJumpVelocity() {
                // Jump velocity logic
            }
        }
        """)
        verifier = Verifier(self.test_dir, build_cmd=["true"])
        success, diags, raw = verifier.run_compiler(target_file="physics.js")
        self.assertFalse(success, "Expected stub methods to be rejected by anti-stub inspector")
        stub_codes = [d.code for d in diags]
        self.assertIn("ANTI_STUB", stub_codes)
        stub_msgs = " ".join(d.message for d in diags)
        self.assertIn("applyGravity", stub_msgs)
        self.assertIn("applyJumpVelocity", stub_msgs)

    def test_detects_hollow_constructor_stub(self):
        # Simulates coin.js / platform.js empty constructors
        coin_js = self.test_dir / "coin.js"
        coin_js.write_text("""
        class Coin {
            constructor() {
                // Coin initialization
            }
        }
        """)
        verifier = Verifier(self.test_dir, build_cmd=["true"])
        success, diags, raw = verifier.run_compiler(target_file="coin.js")
        self.assertFalse(success, "Expected hollow constructor to be flagged as stub")
        self.assertTrue(any(d.code == "ANTI_STUB" and "constructor" in d.message for d in diags))

    def test_allows_implemented_code_with_comments(self):
        # Legitimate implementation with comments should not trigger false positives
        real_js = self.test_dir / "real.js"
        real_js.write_text("""
        class RealPhysics {
            applyGravity(entity) {
                // Gravity calculation logic
                entity.vy += 0.5;
                if (entity.vy > 12) entity.vy = 12;
            }
        }
        """)
        verifier = Verifier(self.test_dir, build_cmd=["true"])
        success, diags, raw = verifier.run_compiler(target_file="real.js")
        self.assertTrue(success, f"Expected real implementation to pass cleanly, got: {diags}")
        self.assertEqual(len(diags), 0)


if __name__ == "__main__":
    unittest.main()
