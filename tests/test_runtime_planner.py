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


if __name__ == "__main__":
    unittest.main()
