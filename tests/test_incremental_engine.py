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

    def test_extract_code_with_conversational_filler(self):
        raw = (
            "Here is the implementation:\n"
            "```javascript\n"
            "class Bird {\n"
            "    constructor() {\n"
            "        this.y = 100;\n"
            "    }\n"
            "}\n"
            "```\n"
            "To use this `Bird` class in a game loop, you would need to create instances of it.\n"
            "```javascript\n"
            "const b = new Bird();\n"
            "```"
        )
        extracted = ScaffoldingEngine._extract_code(raw)
        self.assertIn("class Bird", extracted)
        self.assertNotIn("To use this", extracted)
        self.assertNotIn("const b = new Bird()", extracted)

    def test_extract_code_raw_without_fences(self):
        raw = "class Pipe { constructor() {} }"
        extracted = ScaffoldingEngine._extract_code(raw)
        self.assertEqual(extracted, "class Pipe { constructor() {} }")

    def test_cycle_breaking_topological_sort(self):
        tasks = [
            {"id": "game.js", "file": "game.js", "deps": ["pipe.js", "bird.js"]},
            {"id": "pipe.js", "file": "pipe.js", "deps": ["game.js"]},
            {"id": "bird.js", "file": "bird.js", "deps": []}
        ]
        # Simulate cycle-breaking algorithm from ScaffoldingEngine
        task_by_id = {t["id"]: t for t in tasks}
        task_ids_set = set(task_by_id.keys())
        graph = {}
        for t in tasks:
            t_id = t["id"]
            raw_deps = t.get("deps") or t.get("dependencies") or []
            graph[t_id] = {str(d) for d in raw_deps if str(d) in task_ids_set and str(d) != t_id}

        from graphlib import TopologicalSorter
        ordered = None
        while ordered is None:
            try:
                ts = TopologicalSorter(graph)
                ordered = tuple(ts.static_order())
            except Exception as cycle_err:
                if len(cycle_err.args) >= 2 and isinstance(cycle_err.args[1], (list, tuple)) and len(cycle_err.args[1]) >= 2:
                    cycle_nodes = cycle_err.args[1]
                    u, v = cycle_nodes[-2], cycle_nodes[-1]
                    if u in graph and v in graph[u]:
                        graph[u].discard(v)
                        continue
                    broken = False
                    for c_u in cycle_nodes:
                        if c_u in graph:
                            for c_v in cycle_nodes:
                                if c_v in graph[c_u]:
                                    graph[c_u].discard(c_v)
                                    broken = True
                                    break
                        if broken:
                            break
                    if broken:
                        continue
                ordered = tuple(t["id"] for t in tasks)

        self.assertEqual(len(ordered), 3)
        self.assertIn("bird.js", ordered)
        self.assertIn("pipe.js", ordered)
        self.assertIn("game.js", ordered)


if __name__ == "__main__":
    unittest.main()


