import unittest
from graphlib import TopologicalSorter
from antcoder.engine import ScaffoldingEngine


class TestRuntimePlanner(unittest.TestCase):
    def test_json_parse_target_runtime(self):
        raw_output = """
        ```json
        {
            "target_runtime": "browser-vanilla",
            "dag": [
                {"id": "physics", "file": "physics.js", "deps": [], "contract": "class Physics"},
                {"id": "player", "file": "player.js", "deps": ["physics"], "contract": "class Player"},
                {"id": "game", "file": "game.js", "deps": ["player"], "contract": "class Game"}
            ]
        }
        ```
        """
        parsed = ScaffoldingEngine._parse_json_safely(raw_output)
        self.assertEqual(parsed.get("target_runtime"), "browser-vanilla")
        self.assertEqual(len(parsed.get("dag")), 3)

    def test_topological_script_order_for_html(self):
        dag_tasks = [
            {"id": "game", "file": "game.js", "deps": ["player", "physics"]},
            {"id": "player", "file": "player.js", "deps": ["physics"]},
            {"id": "physics", "file": "physics.js", "deps": []},
            {"id": "index", "file": "index.html", "deps": ["game"]},
        ]
        graph = {t["id"]: set(t["deps"]) for t in dag_tasks}
        task_by_id = {t["id"]: t for t in dag_tasks}

        ts = TopologicalSorter(graph)
        ordered_ids = list(ts.static_order())

        # Expected order: physics -> player -> game -> index
        ordered_js = [
            task_by_id[tid]["file"]
            for tid in ordered_ids
            if task_by_id[tid]["file"].endswith(".js")
        ]
        self.assertEqual(ordered_js, ["physics.js", "player.js", "game.js"])

        script_tags = "\n".join([f'    <script src="{f}"></script>' for f in ordered_js])
        self.assertIn('<script src="physics.js"></script>', script_tags)
        self.assertIn('<script src="player.js"></script>', script_tags)
        self.assertIn('<script src="game.js"></script>', script_tags)
        # Verify physics appears before player, and player before game
        self.assertTrue(script_tags.find("physics.js") < script_tags.find("player.js"))
        self.assertTrue(script_tags.find("player.js") < script_tags.find("game.js"))

    def test_dict_based_dag_tasks(self):
        # Simulates the Flappy Bird planner output format
        raw_output = """
        {
            "target_runtime": "browser-vanilla",
            "index.html": {
                "deps": ["game.js"],
                "contract": "HTML runner"
            },
            "game.js": {
                "deps": ["bird.js", "pipe.js"],
                "contract": "Main game loop"
            },
            "bird.js": {
                "deps": [],
                "contract": "Bird physics"
            }
        }
        """
        parsed = ScaffoldingEngine._parse_json_safely(raw_output)
        self.assertEqual(parsed.get("target_runtime"), "browser-vanilla")

        # Emulate engine task normalization
        raw_tasks = parsed.get("dag") or []
        if not raw_tasks and isinstance(parsed, dict):
            candidate_tasks = []
            for k, v in parsed.items():
                if k in ("target_runtime", "version", "architecture", "type", "description", "goal"):
                    continue
                if isinstance(v, dict):
                    if "file" not in v and any(k.endswith(ext) for ext in [".js", ".ts", ".html"]):
                        v["file"] = k
                    if "id" not in v:
                        v["id"] = k
                    candidate_tasks.append(v)
            raw_tasks = candidate_tasks

        self.assertEqual(len(raw_tasks), 3)
        files = {t["file"] for t in raw_tasks}
        self.assertEqual(files, {"index.html", "game.js", "bird.js"})


if __name__ == "__main__":
    unittest.main()
