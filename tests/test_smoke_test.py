import unittest
import tempfile
import shutil
from pathlib import Path

from antcoder.verifier import Verifier


class TestBrowserSmokeTest(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_valid_html_canvas_passes_smoke_test(self):
        html = self.test_dir / "index.html"
        html.write_text("""<!DOCTYPE html>
        <html>
        <body>
            <canvas id="gameCanvas" width="720" height="420"></canvas>
            <script src="game.js"></script>
        </body>
        </html>
        """)

        game = self.test_dir / "game.js"
        game.write_text("""
        window.addEventListener('DOMContentLoaded', () => {
            const canvas = document.getElementById('gameCanvas');
            const ctx = canvas.getContext('2d');
            ctx.fillRect(0, 0, 100, 100);
        });
        """)

        verifier = Verifier(self.test_dir, build_cmd=["true"])
        diags = verifier.run_smoke_test("index.html")
        self.assertEqual(len(diags), 0, f"Expected smoke test to pass, but got: {diags}")

    def test_broken_html_runtime_error_fails_smoke_test(self):
        html = self.test_dir / "index.html"
        html.write_text("""<!DOCTYPE html>
        <html>
        <body>
            <canvas id="gameCanvas"></canvas>
            <script src="game.js"></script>
        </body>
        </html>
        """)

        # References non-existent element 'brokenCanvas' causing TypeError
        game = self.test_dir / "game.js"
        game.write_text("""
        const canvas = document.getElementById('brokenCanvas');
        const ctx = canvas.getContext('2d');
        """)

        verifier = Verifier(self.test_dir, build_cmd=["true"])
        diags = verifier.run_smoke_test("index.html")
        self.assertGreater(len(diags), 0, "Expected smoke test to detect null getContext error")
        self.assertEqual(diags[0].code, "BROWSER_RUNTIME_ERROR")
        self.assertIn("game.js", diags[0].file)
        self.assertIn("getContext", diags[0].message)


if __name__ == "__main__":
    unittest.main()
