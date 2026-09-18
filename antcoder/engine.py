"""
Autonomous Scaffolding Engine:
The core deterministic state machine that orchestrates Planner LoRA,
Builder LoRA, Compiler verification (tsc), Fixer LoRA, and Git isolation.
"""

import os
import uuid
import time
import json
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from graphlib import TopologicalSorter

from .git_manager import GitManager
from .verifier import Verifier, Diagnostic
from .model_client import BaseModelClient


class ScaffoldingEngine:
    def __init__(
        self,
        repo_path: Path,
        model_client: BaseModelClient,
        build_cmd: Optional[list] = None,
        test_cmd: Optional[list] = None,
        max_fix_retries: int = 3,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ):
        self.repo_path = Path(repo_path).resolve()
        self.git = GitManager(self.repo_path)
        self.verifier = Verifier(self.repo_path, build_cmd=build_cmd, test_cmd=test_cmd)
        self.model_client = model_client
        self.max_fix_retries = max_fix_retries
        self.event_callback = event_callback or (lambda event, data: None)

    def _emit(self, event: str, data: Dict[str, Any]):
        self.event_callback(event, data)

    def execute_feature_goal(
        self,
        goal_description: str,
        repo_summary: Optional[str] = None,
        branch_prefix: str = "antcoder/feature",
    ) -> Dict[str, Any]:
        """
        Full-Spectrum Multi-Agent Autonomous Pipeline:
        1. Query Planner LoRA -> Generates DAG with contracts & dependency graph
        2. Topologically sort the DAG (ensuring acyclicity)
        3. For each task in the DAG:
           - Ingest prior task outputs/types
           - Query Builder LoRA -> Implement contract
           - Run TypeScript compiler (tsc)
           - If compiler errors occur -> Enter Fixer LoRA loop
           - Verify patch resolution
        4. Run test suite
        5. Atomic Git commit to feature branch or rollback
        """
        task_id = str(uuid.uuid4())[:8]
        branch_name = f"{branch_prefix}-{task_id}"
        telemetry = {
            "task_id": task_id,
            "goal": goal_description,
            "status": "PENDING",
            "branch": None,
            "dag": [],
            "completed_tasks": [],
            "total_fix_attempts": 0,
            "logs": [],
        }

        def log(msg: str):
            telemetry["logs"].append(f"{time.strftime('%H:%M:%S')} - {msg}")

        # 1. Isolate workspace on a new feature branch
        orig_branch = self.git.get_current_branch()
        self.git.create_feature_branch(branch_name)
        log(f"Created isolated Git feature branch: {branch_name}")
        self._emit("branch_created", {"branch": branch_name, "task_id": task_id})

        try:
            # 2. Query Planner LoRA for Architectural DAG
            self._emit("planner_start", {"goal": goal_description})
            planner_prompt = (
                f"GOAL SPECIFICATION:\n{goal_description}\n\n"
                f"{('REPOSITORY CONTEXT:\n' + repo_summary + '\n\n') if repo_summary else ''}"
                "Decompose this feature into a strict topological JSON DAG. Each node must define 'id', 'file', 'deps', and explicit 'contract' interfaces."
            )
            planner_messages = [
                {
                    "role": "system",
                    "content": "You are an autonomous software architect. When given a codebase context and user feature specification, output ONLY a valid JSON plan containing a Directed Acyclic Graph (DAG) of tasks with strict scalability guardrails, layered architecture, and explicit TypeScript contracts. Output no conversational filler."
                },
                {"role": "user", "content": planner_prompt},
            ]

            planner_raw = self.model_client.query(planner_messages, model_type="planner")

            # Clean JSON if formatted in markdown block
            clean_plan = planner_raw.strip()
            if clean_plan.startswith("```json"):
                clean_plan = clean_plan[7:]
            if clean_plan.startswith("```"):
                clean_plan = clean_plan[3:]
            if clean_plan.endswith("```"):
                clean_plan = clean_plan[:-3]
            clean_plan = clean_plan.strip()

            plan_dict = json.loads(clean_plan)
            dag_tasks = plan_dict.get("dag") or plan_dict.get("tasks") or []
            if not dag_tasks:
                raise ValueError("Planner failed to generate valid 'dag' task nodes.")

            log(f"Planner synthesized {len(dag_tasks)} task node(s) in DAG.")
            telemetry["dag"] = dag_tasks

            # 3. Topological Sort
            graph = {}
            task_by_id = {}
            for t in dag_tasks:
                t_id = t["id"]
                task_by_id[t_id] = t
                graph[t_id] = set(t.get("deps") or t.get("dependencies") or [])

            ts = TopologicalSorter(graph)
            ordered_task_ids = tuple(ts.static_order())
            self._emit("planner_complete", {
                "dag": dag_tasks,
                "order": ordered_task_ids
            })

            # 4. Iterate over DAG nodes
            for step_idx, t_id in enumerate(ordered_task_ids, start=1):
                task = task_by_id.get(t_id)
                if not task:
                    continue
                target_file = task["file"]
                spec = task["contract"]

                self._emit("task_start", {
                    "task_id": t_id,
                    "file": target_file,
                    "index": step_idx,
                    "total": len(ordered_task_ids)
                })

                # Context gathering: prior dependencies
                deps = task.get("deps") or []
                context_parts = []
                for dep_id in deps:
                    dep_task = task_by_id.get(dep_id)
                    if dep_task and (self.repo_path / dep_task["file"]).exists():
                        with open(self.repo_path / dep_task["file"], "r", encoding="utf-8") as f:
                            context_parts.append(f"// Dependency from {dep_task['file']}:\n{f.read()}")
                context_str = "\n\n".join(context_parts) if context_parts else None

                # Query Builder
                builder_prompt = (
                    f"FILE: {target_file}\n\n"
                    f"{('MODULE CONTEXT:\n' + context_str + '\n\n') if context_str else ''}"
                    f"TASK SPECIFICATION:\n"
                    f"Implement the TypeScript code satisfying this exact contract:\n"
                    f"```typescript\n{spec}\n```"
                )
                builder_messages = [
                    {
                        "role": "system",
                        "content": "You are an autonomous TypeScript software engineer. Implement the contract with 100% type safety and zero placeholders. Output ONLY the code."
                    },
                    {"role": "user", "content": builder_prompt},
                ]

                impl_code = self.model_client.query(builder_messages, model_type="builder")
                clean_impl = impl_code.strip()
                for prefix in ["```typescript", "```ts", "```"]:
                    if clean_impl.startswith(prefix):
                        clean_impl = clean_impl[len(prefix):].strip()
                if clean_impl.endswith("```"):
                    clean_impl = clean_impl[:-3].strip()

                abs_target = self.repo_path / target_file
                abs_target.parent.mkdir(parents=True, exist_ok=True)
                with open(abs_target, "w", encoding="utf-8") as f:
                    f.write(f"{clean_impl}\n")

                self._emit("builder_complete", {
                    "task_id": t_id,
                    "file": target_file,
                    "lines": len(clean_impl.splitlines())
                })

                # Verify with compiler
                self._emit("verifier_start", {"task_id": t_id})
                success, diagnostics, raw_out = self.verifier.run_compiler()
                if success:
                    self._emit("verifier_pass", {"task_id": t_id, "errors": 0})
                else:
                    self._emit("verifier_fail", {
                        "task_id": t_id,
                        "errors": len(diagnostics),
                        "diagnostics": [d.to_dict() for d in diagnostics[:3]]
                    })
                    fix_attempt = 0
                    while not success and fix_attempt < self.max_fix_retries:
                        fix_attempt += 1
                        telemetry["total_fix_attempts"] += 1
                        self._emit("fixer_start", {
                            "task_id": t_id,
                            "attempt": fix_attempt,
                            "max": self.max_fix_retries
                        })

                        diag = diagnostics[0] if diagnostics else None
                        if not diag:
                            break
                        code_context = self.verifier.extract_context(diag.file, diag.line)

                        fixer_prompt = (
                            f"FILE: {diag.file}\n\n"
                            f"DIAGNOSTIC:\n{diag.raw}\n\n"
                            f"CODE CONTEXT:\n{code_context}"
                        )
                        fixer_messages = [
                            {
                                "role": "system",
                                "content": "You are an autonomous compiler error repair engine. Output ONLY a unified diff patch that fixes the error."
                            },
                            {"role": "user", "content": fixer_prompt},
                        ]

                        diff_patch = self.model_client.query(fixer_messages, model_type="fixer")
                        patch_ok, patch_msg = self.git.apply_patch(diff_patch)
                        if not patch_ok:
                            self._emit("fixer_patch_failed", {"task_id": t_id, "error": patch_msg})
                        else:
                            self._emit("fixer_patch_applied", {"task_id": t_id})

                        success, diagnostics, raw_out = self.verifier.run_compiler()
                        if success:
                            self._emit("fixer_resolved", {"task_id": t_id, "attempt": fix_attempt})
                            break

                if not success:
                    self._emit("task_abort", {"task_id": t_id, "reason": "compiler_error_unresolved"})
                    self.git.rollback()
                    self.git._run(["git", "checkout", orig_branch])
                    telemetry["status"] = f"FAILED_ON_TASK_{t_id}"
                    return telemetry

                telemetry["completed_tasks"].append(t_id)
                self._emit("task_complete", {"task_id": t_id})

            # 5. Run unit tests if configured
            test_ok, test_out = self.verifier.run_tests()
            if not test_ok:
                self._emit("tests_failed", {"output": test_out})
                self.git.rollback()
                self.git._run(["git", "checkout", orig_branch])
                telemetry["status"] = "FAILED_TESTS"
                return telemetry

            # 6. Commit full feature to branch
            commit_msg = f"feat(antcoder): {goal_description}\n\nTasks implemented: {', '.join(ordered_task_ids)}\nTask-ID: {task_id}"
            committed, commit_info = self.git.commit(commit_msg)
            telemetry["status"] = "SUCCESS"
            telemetry["branch"] = branch_name
            self._emit("feature_complete", {
                "branch": branch_name,
                "commit": commit_info,
                "tasks": ordered_task_ids
            })
            return telemetry

        except Exception as e:
            self._emit("fatal_error", {"error": str(e)})
            self.git.rollback()
            self.git._run(["git", "checkout", orig_branch], check=False)
            telemetry["status"] = "ERROR"
            telemetry["error"] = str(e)
            return telemetry
