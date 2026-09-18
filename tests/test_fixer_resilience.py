import unittest
import tempfile
import shutil
from pathlib import Path

from antcoder.git_manager import GitManager


class TestFixerResilience(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        # Init git repo
        import subprocess
        subprocess.run(["git", "init"], cwd=self.test_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.test_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=self.test_dir, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=self.test_dir, capture_output=True)
        self.git = GitManager(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_search_replace_block_patching(self):
        target = self.test_dir / "bird.js"
        target.write_text("""class Bird {
    constructor(x, y) {
        this.x = x;
        this.y = y;
    }
    }
}
""")
        patch = """
<<<<<<< SEARCH
    constructor(x, y) {
        this.x = x;
        this.y = y;
    }
    }
=======
    constructor(x, y) {
        this.x = x;
        this.y = y;
    }
>>>>>>>
"""
        ok, msg = self.git.apply_patch(patch, fallback_file="bird.js")
        self.assertTrue(ok, f"Search/Replace failed: {msg}")
        updated = target.read_text()
        self.assertNotIn("}\n    }\n}", updated)
        self.assertIn("class Bird {\n    constructor(x, y) {\n        this.x = x;\n        this.y = y;\n    }\n}", updated)

    def test_context_hunk_patching(self):
        target = self.test_dir / "math.js"
        target.write_text("function add(a, b) {\n    return a - b;\n}\n")

        diff = """--- a/math.js
+++ b/math.js
@@ -999,999 @@ (deliberately wrong line numbers)
 function add(a, b) {
-    return a - b;
+    return a + b;
 }
"""
        ok, msg = self.git.apply_patch(diff, fallback_file="math.js")
        self.assertTrue(ok, f"Context hunk failed: {msg}")
        self.assertIn("return a + b;", target.read_text())

    def test_code_block_fallback_replacement(self):
        target = self.test_dir / "config.js"
        target.write_text("// broken config\n")

        clean_code = """```javascript
const config = {
    gravity: 0.6,
    speed: 3
};
```"""
        ok, msg = self.git.apply_patch(clean_code, fallback_file="config.js")
        self.assertTrue(ok, f"Full rewrite fallback failed: {msg}")
        self.assertIn("gravity: 0.6", target.read_text())


if __name__ == "__main__":
    unittest.main()
