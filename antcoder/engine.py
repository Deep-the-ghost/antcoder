"""
Autonomous Scaffolding Engine:
The core deterministic state machine that orchestrates Planner LoRA,
Builder LoRA, Compiler verification (tsc), Fixer LoRA, and Git isolation.
"""

import os
import re
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

    @staticmethod
    def _parse_json_safely(raw_text: str) -> dict:
        """Robustly extract and parse JSON from model output."""
        clean = raw_text.strip()

        # 1. Direct parse attempt
        try:
            return json.loads(clean)
        except Exception:
            pass

        # 2. Strip markdown blocks if present
        for prefix in ["```json", "```JSON", "```"]:
            if prefix in clean:
                parts = clean.split(prefix, 1)
                if len(parts) > 1:
                    code_part = parts[1]
                    if "```" in code_part:
                        clean = code_part.split("```", 1)[0].strip()
                        break

        try:
            return json.loads(clean)
        except Exception:
            pass

        # 3. Extract outermost { ... }
        first_brace = clean.find("{")
        last_brace = clean.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            extracted = clean[first_brace:last_brace + 1]
            try:
                return json.loads(extracted)
            except Exception:
                # Repair trailing commas: ,} or ,]
                repaired = re.sub(r",\s*([\]}])", r"\1", extracted)
                try:
                    return json.loads(repaired)
                except Exception:
                    pass

        # 4. Extract outermost [ ... ]
        first_bracket = clean.find("[")
        last_bracket = clean.rfind("]")
        if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
            extracted = clean[first_bracket:last_bracket + 1]
            try:
                res = json.loads(extracted)
                if isinstance(res, list):
                    return {"dag": res}
            except Exception:
                pass

        raise ValueError(f"Could not parse valid JSON DAG from planner output. Snippet: {raw_text[:200]}")

    @staticmethod
    def _extract_code(raw_text: str) -> str:
        """
        Extract pure executable code from model output.
        Sub-8B models frequently wrap code in markdown fences (```lang ... ```)
        and append conversational postscripts or secondary code examples.
        """
        text = raw_text.strip()

        # 1. Search for markdown code fence blocks: ```lang ... ```
        pattern = r"```(?:[a-zA-Z0-9_\-+]+)?\r?\n(.*?)```"
        matches = list(re.finditer(pattern, text, re.DOTALL))
        if matches:
            return matches[0].group(1).strip()

        # 2. Check for unclosed fence at start (e.g. truncated or missing closing fence)
        unclosed = re.match(r"^```(?:[a-zA-Z0-9_\-+]+)?\r?\n(.*)$", text, re.DOTALL)
        if unclosed:
            return unclosed.group(1).strip()

        # 3. Fallback: Strip leading/trailing code fences if present
        for prefix in ["```typescript", "```javascript", "```html", "```js", "```ts", "```python", "```py", "```"]:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        if text.endswith("```"):
            text = text[:-3].strip()

        return text


    def scan_repository(self) -> str:
        """
        Scans the repository to produce a concise architectural summary of existing files,
        exported classes/functions, and project structure for incremental planning.
        """
        summary_lines = []
        ignored_dirs = {".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__"}

        all_files = []
        for p in self.repo_path.rglob("*"):
            if not p.is_file():
                continue
            if any(part in ignored_dirs for part in p.parts):
                continue
            all_files.append(p)

        if not all_files:
            return ""

        summary_lines.append(f"Found {len(all_files)} existing file(s) in repository:")
        for f in sorted(all_files, key=lambda x: str(x)):
            try:
                rel = str(f.relative_to(self.repo_path))
            except Exception:
                rel = f.name
            size = f.stat().st_size

            # Extract key signatures if code file
            sigs = []
            if f.suffix in [".js", ".mjs", ".ts", ".tsx"]:
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                    classes = re.findall(r'class\s+([A-Za-z0-9_$]+)', text)
                    functions = re.findall(r'(?:function\s+|const\s+|let\s+)([A-Za-z0-9_$]+)\s*=\s*(?:function|\([^)]*\)\s*=>)', text)
                    if classes:
                        sigs.append("classes: " + ", ".join(classes[:5]))
                    if functions:
                        sigs.append("functions: " + ", ".join(functions[:5]))
                except Exception:
                    pass
            elif f.suffix == ".html":
                sigs.append("HTML entrypoint")

            sig_str = f" ({'; '.join(sigs)})" if sigs else ""
            summary_lines.append(f"  - {rel} [{size} bytes]{sig_str}")

        return "\n".join(summary_lines)

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

        # Ingest existing repository context if not explicitly provided
        if repo_summary is None:
            repo_summary = self.scan_repository()

        # 1. Isolate workspace on a new feature branch
        orig_branch = self.git.get_current_branch()
        self.git.create_feature_branch(branch_name)
        log(f"Created isolated Git feature branch: {branch_name}")
        self._emit("branch_created", {"branch": branch_name, "task_id": task_id})

        try:
            # 2. Query Planner LoRA for Architectural DAG
            self._emit("planner_start", {"goal": goal_description})

            is_incremental = bool(repo_summary and repo_summary.strip())
            if is_incremental:
                planner_prompt = (
                    f"GOAL SPECIFICATION:\n{goal_description}\n\n"
                    f"EXISTING REPOSITORY CONTEXT:\n{repo_summary}\n\n"
                    "INCREMENTAL UPDATE RULES:\n"
                    "1. You are modifying an EXISTING repository. Only plan DAG tasks for files that need to be MODIFIED or CREATED.\n"
                    "2. Reuse and build on top of existing components, classes, and canvas elements. Do NOT duplicate or needlessly recreate working files.\n"
                    "3. Ensure the complete application remains functional after changes.\n"
                    "4. Output ONLY the JSON DAG with target_runtime."
                )
                planner_messages = [
                    {
                        "role": "system",
                        "content": "You are an autonomous software architect performing an incremental update on an existing codebase. Output ONLY a valid JSON plan containing a Directed Acyclic Graph (DAG) for the modified or new files. Preserve existing working modules."
                    },
                    {"role": "user", "content": planner_prompt},
                ]
            else:
                planner_prompt = (
                    f"GOAL SPECIFICATION:\n{goal_description}\n\n"
                    "Decompose this feature into a strict topological JSON DAG. Each node must define 'id', 'file', 'deps', and explicit 'contract' interfaces.\n"
                    "Declare 'target_runtime' in the JSON root ('browser-vanilla' for web/canvas/games, 'node-esm' for backend/modules).\n"
                    "IMPORTANT: If building a game or interactive visual application, ALWAYS include an 'index.html' file in the DAG so the user can open and play it directly in their browser."
                )
                planner_messages = [
                    {
                        "role": "system",
                        "content": "You are an autonomous software architect. When given a codebase context and user feature specification, output ONLY a valid JSON plan containing a Directed Acyclic Graph (DAG) of tasks with strict scalability guardrails, layered architecture, explicit contracts, and target_runtime. For games or web apps, set target_runtime to 'browser-vanilla' and include an index.html file so it is immediately playable in a browser. Output no conversational filler."
                    },
                    {"role": "user", "content": planner_prompt},
                ]

            planner_raw = self.model_client.query(planner_messages, model_type="planner")

            # Robust JSON extraction & normalization
            plan_dict = self._parse_json_safely(planner_raw)
            raw_tasks = plan_dict.get("dag") or plan_dict.get("tasks") or plan_dict.get("steps") or []
            if isinstance(raw_tasks, dict):
                dict_tasks = []
                for k, v in raw_tasks.items():
                    if isinstance(v, dict):
                        if "file" not in v:
                            v["file"] = k
                        if "id" not in v:
                            v["id"] = k
                        dict_tasks.append(v)
                    elif isinstance(v, str):
                        dict_tasks.append({"id": k, "file": k, "contract": v, "deps": []})
                raw_tasks = dict_tasks
            elif isinstance(plan_dict, list):
                raw_tasks = plan_dict
            elif not raw_tasks and isinstance(plan_dict, dict):
                # Check if the dictionary itself maps filenames or task IDs to task specifications
                candidate_tasks = []
                for k, v in plan_dict.items():
                    if k in ("target_runtime", "version", "architecture", "type", "description", "goal"):
                        continue
                    if isinstance(v, dict):
                        if "file" not in v and any(k.endswith(ext) for ext in [".js", ".ts", ".html", ".py", ".css"]):
                            v["file"] = k
                        if "id" not in v:
                            v["id"] = k
                        candidate_tasks.append(v)
                if candidate_tasks:
                    raw_tasks = candidate_tasks

            # Target runtime detection: planner declared or auto-inferred
            target_runtime = plan_dict.get("target_runtime")
            if target_runtime in ["browser", "web", "vanilla", "html5"]:
                target_runtime = "browser-vanilla"
            elif not target_runtime:
                goal_lower = goal_description.lower()
                if any(k in goal_lower for k in ["game", "canvas", "browser", "html", "mario", "snake", "pong", "play", "flappy"]):
                    target_runtime = "browser-vanilla"
                else:
                    target_runtime = "node-esm"
            log(f"Target execution runtime determined: {target_runtime}")

            if not raw_tasks:
                raise ValueError(f"Planner failed to generate valid 'dag' task nodes. Output preview: {planner_raw[:200]}")

            # Normalize task fields (id, file, contract, deps)
            dag_tasks = []
            for idx, t in enumerate(raw_tasks, start=1):
                if not isinstance(t, dict):
                    continue
                t_id = str(t.get("id") or t.get("name") or t.get("step") or f"node_{idx}")
                t_file = t.get("file") or t.get("file_path") or t.get("path") or f"src/module_{idx}.ts"
                contract_val = (
                    t.get("contract")
                    or t.get("spec")
                    or t.get("actions")
                    or t.get("description")
                    or t.get("interface")
                    or "export interface ModuleInterface {}"
                )
                if isinstance(contract_val, list):
                    t_contract = "\n".join(str(c) for c in contract_val)
                else:
                    t_contract = str(contract_val)

                t_deps = t.get("deps") or t.get("dependencies") or []
                if isinstance(t_deps, str):
                    t_deps = [d.strip() for d in t_deps.split(",") if d.strip()]
                elif not isinstance(t_deps, list):
                    t_deps = []
                dag_tasks.append({
                    "id": t_id,
                    "file": t_file,
                    "contract": t_contract,
                    "deps": [str(d) for d in t_deps],
                    "description": t.get("description", "")
                })

            if not dag_tasks:
                raise ValueError("No actionable tasks could be normalized from the planner DAG.")

            log(f"Planner synthesized {len(dag_tasks)} task node(s) in DAG.")
            telemetry["dag"] = dag_tasks

            # 3. Topological Sort with Autonomous Cycle Breaking
            task_by_id = {t["id"]: t for t in dag_tasks}
            task_ids_set = set(task_by_id.keys())
            graph = {}
            for t in dag_tasks:
                t_id = t["id"]
                raw_deps = t.get("deps") or t.get("dependencies") or []
                graph[t_id] = {str(d) for d in raw_deps if str(d) in task_ids_set and str(d) != t_id}

            ordered_task_ids = None
            while ordered_task_ids is None:
                try:
                    ts = TopologicalSorter(graph)
                    ordered_task_ids = tuple(ts.static_order())
                except Exception as cycle_err:
                    if len(cycle_err.args) >= 2 and isinstance(cycle_err.args[1], (list, tuple)) and len(cycle_err.args[1]) >= 2:
                        cycle_nodes = cycle_err.args[1]
                        u, v = cycle_nodes[-2], cycle_nodes[-1]
                        if u in graph and v in graph[u]:
                            graph[u].discard(v)
                            log(f"Autonomously broke cyclic dependency edge: {u} -> {v}")
                            continue
                        broken = False
                        for c_u in cycle_nodes:
                            if c_u in graph:
                                for c_v in cycle_nodes:
                                    if c_v in graph[c_u]:
                                        graph[c_u].discard(c_v)
                                        log(f"Autonomously broke cyclic dependency edge: {c_u} -> {c_v}")
                                        broken = True
                                        break
                            if broken:
                                break
                        if broken:
                            continue
                    # Fallback if specific cycle could not be isolated
                    ordered_task_ids = tuple(t["id"] for t in dag_tasks)
            self._emit("planner_complete", {
                "dag": dag_tasks,
                "order": ordered_task_ids
            })

            # Extract ordered scripts for index.html injection if applicable
            ordered_js_files = [
                task_by_id[tid]["file"]
                for tid in ordered_task_ids
                if task_by_id.get(tid) and task_by_id[tid]["file"].endswith((".js", ".mjs", ".ts"))
            ]
            script_tags_snippet = "\n".join([f'    <script src="{f}"></script>' for f in ordered_js_files])

            # Pre-scaffold minimal skeletons for all planned files in DAG
            # This prevents premature 'TS2307: Cannot find module' errors when
            # an early node imports a sibling module that is scheduled for later implementation.
            dag_files = {t["file"] for t in dag_tasks if "file" in t}
            for frel in dag_files:
                fpath = self.repo_path / frel
                if not fpath.exists():
                    fpath.parent.mkdir(parents=True, exist_ok=True)
                    fpath.write_text("// Planned module skeleton for AntCoder DAG\nexport {};\n")

            # Auto-provision modern DOM-compatible tsconfig.json if missing
            default_tsconfig = self.repo_path / "tsconfig.json"
            if not default_tsconfig.exists():
                try:
                    default_tsconfig.write_text(json.dumps({
                        "compilerOptions": {
                            "target": "ES2022",
                            "module": "NodeNext",
                            "moduleResolution": "NodeNext",
                            "lib": ["DOM", "DOM.Iterable", "ES2022"],
                            "strict": False,
                            "skipLibCheck": True,
                            "esModuleInterop": True,
                            "allowJs": True,
                            "checkJs": False
                        }
                    }, indent=2), encoding="utf-8")
                except Exception:
                    pass

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

                # Query Builder with extension-aware and runtime-aware instructions
                is_html = target_file.endswith((".html", ".htm"))
                is_js = target_file.endswith((".js", ".mjs"))

                if is_html:
                    builder_prompt = (
                        f"FILE: {target_file}\n\n"
                        f"TARGET RUNTIME: {target_runtime}\n\n"
                        f"REQUIRED SCRIPT TAGS (in dependency order):\n"
                        f"Include these exact script tags in the <body> in this order so dependencies load cleanly:\n"
                        f"{script_tags_snippet}\n\n"
                        f"{('MODULE CONTEXT:\n' + context_str + '\n\n') if context_str else ''}"
                        f"TASK SPECIFICATION:\n"
                        f"Implement the complete HTML file satisfying this contract:\n"
                        f"{spec}\n\n"
                        f"RULES:\n"
                        f"1. Include all necessary HTML5 boilerplate, canvas/DOM containers, responsive CSS styling, and the required <script src='...'> tags in the specified order.\n"
                        f"2. Zero stubs. Output ONLY valid HTML."
                    )
                    builder_messages = [
                        {
                            "role": "system",
                            "content": "You are an autonomous web frontend engineer. Output ONLY valid, complete HTML with responsive CSS styling and functional canvas setup. Zero placeholders."
                        },
                        {"role": "user", "content": builder_prompt},
                    ]
                elif is_js:
                    if target_runtime == "browser-vanilla":
                        builder_prompt = (
                            f"FILE: {target_file}\n\n"
                            f"TARGET RUNTIME: browser-vanilla (Runs directly in browser via file:// or static server)\n\n"
                            f"{('MODULE CONTEXT:\n' + context_str + '\n\n') if context_str else ''}"
                            f"TASK SPECIFICATION:\n"
                            f"Implement the complete JavaScript file satisfying this contract:\n"
                            f"```javascript\n{spec}\n```\n\n"
                            f"RULES:\n"
                            f"1. Write 100% valid modern JavaScript (ES6+). Do NOT include TypeScript type annotations or TypeScript private/public modifiers.\n"
                            f"2. BROWSER SCRIPT COMPATIBILITY: Do NOT use bare 'import ... from ...' statements that fail over file:// protocol without a bundler. Instead, attach classes and functions to globalThis/window (e.g. `(function(root) {{ class Component {{ ... }} root.Component = Component; }})(typeof window !== 'undefined' ? window : globalThis);`).\n"
                            f"3. Ensure all functions, methods, game mechanics, physics, and rendering are fully implemented with ZERO stubs or empty placeholders."
                        )
                    else:
                        builder_prompt = (
                            f"FILE: {target_file}\n\n"
                            f"TARGET RUNTIME: {target_runtime}\n\n"
                            f"{('MODULE CONTEXT:\n' + context_str + '\n\n') if context_str else ''}"
                            f"TASK SPECIFICATION:\n"
                            f"Implement the complete JavaScript file satisfying this contract:\n"
                            f"```javascript\n{spec}\n```\n\n"
                            f"RULES:\n"
                            f"1. Write 100% valid modern JavaScript (ES6+). Do NOT include TypeScript type annotations or TypeScript private/public modifiers.\n"
                            f"2. Ensure all functions, methods, mechanics, and logic are fully implemented with ZERO stubs or empty placeholders.\n"
                            f"3. Support standard Node.js exports/imports."
                        )
                    builder_messages = [
                        {
                            "role": "system",
                            "content": "You are an autonomous JavaScript software engineer. Implement the contract with complete functional code and zero stubs. Never use TypeScript type annotations in .js files. Output ONLY executable JavaScript code."
                        },
                        {"role": "user", "content": builder_prompt},
                    ]
                else:
                    builder_prompt = (
                        f"FILE: {target_file}\n\n"
                        f"{('MODULE CONTEXT:\n' + context_str + '\n\n') if context_str else ''}"
                        f"TASK SPECIFICATION:\n"
                        f"Implement the complete TypeScript file satisfying this contract:\n"
                        f"```typescript\n{spec}\n```\n\n"
                        f"RULES:\n"
                        f"1. You MUST include all necessary 'import ... from ...' statements at the top of the file for any types or classes referenced from other modules.\n"
                        f"2. 100% complete zero-stub code. Output ONLY executable TypeScript code. Fully implement all functions and methods."
                    )
                    builder_messages = [
                        {
                            "role": "system",
                            "content": "You are an autonomous TypeScript software engineer. Always include all required import statements at the top of the file. Implement the contract with 100% type safety and zero placeholders. Output ONLY the code."
                        },
                        {"role": "user", "content": builder_prompt},
                    ]

                impl_code = self.model_client.query(builder_messages, model_type="builder")
                clean_impl = self._extract_code(impl_code)

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
                success, diagnostics, raw_out = self.verifier.run_compiler(target_file=target_file)

                # Filter diagnostics to actionable errors for current node
                # Scoped to target_file so errors in yet-unvisited sibling tasks do not block current task
                target_name = Path(target_file).name
                actionable_diags = [
                    d for d in diagnostics
                    if (d.file == target_file or Path(d.file).name == target_name)
                    and not (d.code == "TS2307" and any(Path(df).stem in d.message for df in dag_files))
                ]

                if success or len(actionable_diags) == 0:
                    self._emit("verifier_pass", {"task_id": t_id, "errors": 0})
                else:
                    self._emit("verifier_fail", {
                        "task_id": t_id,
                        "errors": len(actionable_diags),
                        "diagnostics": [d.to_dict() for d in actionable_diags[:3]]
                    })
                    fix_attempt = 0
                    while not success and fix_attempt < self.max_fix_retries and len(actionable_diags) > 0:
                        fix_attempt += 1
                        telemetry["total_fix_attempts"] += 1
                        self._emit("fixer_start", {
                            "task_id": t_id,
                            "attempt": fix_attempt,
                            "max": self.max_fix_retries
                        })

                        diag = actionable_diags[0]
                        code_context = self.verifier.extract_context(diag.file, diag.line)

                        if len(actionable_diags) > 1:
                            diags_formatted = "\n".join([f"- Line {d.line}: {d.raw}" for d in actionable_diags[:5]])
                            diag_header = f"COMPILER DIAGNOSTICS ({len(actionable_diags)} error(s)):\n{diags_formatted}"
                        else:
                            diag_header = f"DIAGNOSTIC:\n{diag.raw}"

                        if fix_attempt == self.max_fix_retries:
                            # Final retry: ask for complete corrected file
                            fixer_prompt = (
                                f"FILE: {diag.file}\n\n"
                                f"{diag_header}\n\n"
                                f"CODE CONTEXT:\n{code_context}\n\n"
                                f"Prior patch attempts failed. Directly output the 100% complete, corrected file with all errors fixed."
                            )
                        else:
                            fixer_prompt = (
                                f"FILE: {diag.file}\n\n"
                                f"{diag_header}\n\n"
                                f"CODE CONTEXT:\n{code_context}\n\n"
                                f"Fix the diagnostic errors. You may output a SEARCH/REPLACE block:\n"
                                f"<<<<<<< SEARCH\n"
                                f"exact lines from code\n"
                                f"=======\n"
                                f"corrected lines\n"
                                f">>>>>>>\n"
                                f"OR a unified diff patch. Output ONLY the patch block."
                            )

                        fixer_messages = [
                            {
                                "role": "system",
                                "content": "You are an autonomous compiler error repair engine. Output a SEARCH/REPLACE block or unified diff patch that fixes the error."
                            },
                            {"role": "user", "content": fixer_prompt},
                        ]

                        diff_patch = self.model_client.query(fixer_messages, model_type="fixer")
                        patch_ok, patch_msg = self.git.apply_patch(diff_patch, fallback_file=diag.file or target_file)
                        if not patch_ok:
                            self._emit("fixer_patch_failed", {"task_id": t_id, "error": patch_msg})
                        else:
                            self._emit("fixer_patch_applied", {"task_id": t_id})

                        success, diagnostics, raw_out = self.verifier.run_compiler(target_file=target_file)
                        actionable_diags = [
                            d for d in diagnostics
                            if (d.file == target_file or Path(d.file).name == target_name)
                            and not (d.code == "TS2307" and any(Path(df).stem in d.message for df in dag_files))
                        ]
                        if success or len(actionable_diags) == 0:
                            self._emit("fixer_resolved", {"task_id": t_id, "attempt": fix_attempt})
                            break

                    # Strict Verification Gate: Abort if unresolved compiler errors remain
                    if not success and len(actionable_diags) > 0:
                        self._emit("task_failed", {
                            "task_id": t_id,
                            "file": target_file,
                            "errors": len(actionable_diags),
                            "diagnostics": [d.to_dict() for d in actionable_diags]
                        })
                        log(f"Verification failed to resolve for task {t_id} ({target_file}). Aborting.")
                        self.git.rollback()
                        self.git._run(["git", "checkout", orig_branch], check=False)
                        telemetry["status"] = "FAILED_VERIFICATION"
                        telemetry["failed_task"] = t_id
                        telemetry["unresolved_diagnostics"] = [d.to_dict() for d in actionable_diags]
                        return telemetry

                telemetry["completed_tasks"].append(t_id)
                self._emit("task_complete", {"task_id": t_id})

            # 5. Global Feature Gate: Verify integrated repository across all files
            self._emit("verifier_start", {"task_id": "global_gate"})
            global_ok, global_diags, global_raw = self.verifier.run_compiler()
            global_actionable = [
                d for d in global_diags
                if not (d.code == "TS2307" and any(Path(df).stem in d.message for df in dag_files))
            ]
            if not global_ok and len(global_actionable) > 0:
                self._emit("verifier_fail", {
                    "task_id": "global_gate",
                    "errors": len(global_actionable),
                    "diagnostics": [d.to_dict() for d in global_actionable[:3]]
                })
                log(f"Global verification gate failed with {len(global_actionable)} error(s). Rolling back.")
                self.git.rollback()
                self.git._run(["git", "checkout", orig_branch], check=False)
                telemetry["status"] = "FAILED_VERIFICATION"
                telemetry["unresolved_diagnostics"] = [d.to_dict() for d in global_actionable]
                return telemetry

            # 6. Run unit tests if configured
            test_ok, test_out = self.verifier.run_tests()
            if not test_ok:
                self._emit("tests_failed", {"output": test_out})
                self.git.rollback()
                self.git._run(["git", "checkout", orig_branch])
                telemetry["status"] = "FAILED_TESTS"
                return telemetry

            # 7. Commit full feature to branch
            commit_msg = f"feat(antcoder): {goal_description}\n\nTasks implemented: {', '.join(ordered_task_ids)}\nTask-ID: {task_id}"
            committed, commit_info = self.git.commit(commit_msg)

            # Auto-merge verified feature into working branch so files are immediately accessible
            try:
                self.git._run(["git", "checkout", orig_branch])
                self.git._run(["git", "merge", branch_name, "--no-edit"])
            except Exception:
                pass

            telemetry["status"] = "SUCCESS"
            telemetry["branch"] = orig_branch
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
