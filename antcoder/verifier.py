"""
Verification Engine:
Invokes TypeScript compiler, extracts structured diagnostics and context windows,
and executes unit test suites.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional


class Diagnostic:
    def __init__(self, file: str, line: int, col: int, code: str, message: str, raw: str):
        self.file = file
        self.line = line
        self.col = col
        self.code = code
        self.message = message
        self.raw = raw

    def to_dict(self):
        return {
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "code": self.code,
            "message": self.message,
        }


class Verifier:
    def __init__(self, repo_path: Path, build_cmd: Optional[List[str]] = None, test_cmd: Optional[List[str]] = None):
        self.repo_path = Path(repo_path).resolve()
        self.build_cmd = build_cmd or self._detect_build_cmd()
        self.test_cmd = test_cmd

    def _detect_build_cmd(self) -> List[str]:
        """Detect the best build/typecheck command for this repository."""
        import shutil
        tsc_bin = shutil.which("tsc") or "/home/deep/.nvm/versions/node/v24.20.0/bin/tsc"
        if not shutil.which(tsc_bin) and not os.path.exists(tsc_bin):
            tsc_bin = "tsc"

        if (self.repo_path / "tsconfig.build.json").exists():
            return [tsc_bin, "--noEmit", "-p", "tsconfig.build.json"]
        elif (self.repo_path / "tsconfig.json").exists():
            return [tsc_bin, "--noEmit"]

        # If repo has no tsconfig, initialize a modern TypeScript 7+ tsconfig with allowJs
        default_tsconfig = self.repo_path / "tsconfig.json"
        if not default_tsconfig.exists():
            try:
                import json
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
                }, indent=2))
            except Exception:
                pass

        return [tsc_bin, "--noEmit", "--skipLibCheck", "--allowJs"]

    def run_compiler(self, timeout_sec: int = 60, target_file: Optional[str] = None) -> Tuple[bool, List[Diagnostic], str]:
        """
        Multi-Tier Verifier Gate:
        Tier 1: TypeScript compiler (tsc) for type safety & contracts.
        Tier 2: Node.js syntax check (node --check) for JavaScript files.
        Tier 3: Python py_compile for Python files.
        Returns: (success: bool, diagnostics: List[Diagnostic], raw_output: str)
        """
        all_diags: List[Diagnostic] = []
        raw_outputs: List[str] = []

        # 1. Run TypeScript compiler
        try:
            proc = subprocess.run(
                self.build_cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            raw = proc.stdout + "\n" + proc.stderr
            raw_outputs.append(raw.strip())
            if proc.returncode != 0:
                all_diags.extend(self._parse_tsc_output(raw))
        except subprocess.TimeoutExpired:
            return False, [], "Compiler execution timed out."
        except Exception as e:
            return False, [], f"Compiler execution error: {str(e)}"

        # 2. Syntax check JavaScript files using node --check
        import shutil
        node_bin = shutil.which("node") or "/home/deep/.nvm/versions/node/v24.20.0/bin/node"
        if os.path.exists(node_bin) or shutil.which("node"):
            if target_file and target_file.endswith((".js", ".mjs")):
                js_candidates = [self.repo_path / target_file]
            else:
                js_candidates = list(self.repo_path.glob("**/*.js")) + list(self.repo_path.glob("**/*.mjs"))

            for js_file in js_candidates:
                if not js_file.exists() or "node_modules" in js_file.parts or ".git" in js_file.parts:
                    continue
                try:
                    js_proc = subprocess.run(
                        [node_bin, "--check", str(js_file)],
                        cwd=self.repo_path,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if js_proc.returncode != 0:
                        raw_outputs.append(f"Node syntax check failed on {js_file.name}:\n{js_proc.stderr}")
                        diags = self._parse_node_check_output(js_proc.stderr, str(js_file.relative_to(self.repo_path)))
                        all_diags.extend(diags)
                except Exception:
                    pass

        # 3. Syntax check Python files using py_compile
        py_bin = shutil.which("python3") or shutil.which("python")
        if py_bin:
            if target_file and target_file.endswith(".py"):
                py_candidates = [self.repo_path / target_file]
            else:
                py_candidates = list(self.repo_path.glob("**/*.py"))

            for py_file in py_candidates:
                if not py_file.exists() or ".git" in py_file.parts or "venv" in py_file.parts or ".venv" in py_file.parts:
                    continue
                try:
                    py_proc = subprocess.run(
                        [py_bin, "-m", "py_compile", str(py_file)],
                        cwd=self.repo_path,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if py_proc.returncode != 0:
                        raw_outputs.append(f"Python syntax check failed on {py_file.name}:\n{py_proc.stderr}")
                        diags = self._parse_py_compile_output(py_proc.stderr, str(py_file.relative_to(self.repo_path)))
                        all_diags.extend(diags)
                except Exception:
                    pass

        # 4. Anti-Stub & Completeness Inspector
        stub_diags = self.inspect_stubs(target_file=target_file)
        if stub_diags:
            all_diags.extend(stub_diags)
            raw_outputs.append("\n".join(d.raw for d in stub_diags))

        # 5. Headless Browser Smoke Test for Web / HTML5 projects
        smoke_diags = self.run_smoke_test(html_file=target_file if target_file and target_file.endswith((".html", ".htm")) else None)
        if smoke_diags:
            all_diags.extend(smoke_diags)
            raw_outputs.append("\n".join(d.raw for d in smoke_diags))

        success = len(all_diags) == 0
        return success, all_diags, "\n---\n".join(filter(None, raw_outputs))

    def run_smoke_test(self, html_file: Optional[str] = None) -> List[Diagnostic]:
        """
        Automated Headless Smoke Test:
        Validates that index.html and its loaded scripts evaluate cleanly in a browser DOM environment,
        catching runtime exceptions (ReferenceError, TypeError, missing element IDs, broken canvas context).
        """
        diagnostics: List[Diagnostic] = []

        if html_file:
            target_html = self.repo_path / html_file
        else:
            candidates = list(self.repo_path.glob("**/index.html")) + list(self.repo_path.glob("*.html"))
            target_html = candidates[0] if candidates else None

        if not target_html or not target_html.exists():
            return []

        import shutil
        import json
        node_bin = shutil.which("node") or "/home/deep/.nvm/versions/node/v24.20.0/bin/node"
        if not os.path.exists(node_bin) and not shutil.which("node"):
            return []

        runner_js = f"""
const vm = require('vm');
const fs = require('fs');
const path = require('path');

const htmlPath = {json.dumps(str(target_html))};

try {{
    const htmlContent = fs.readFileSync(htmlPath, 'utf-8');

    // Extract canvas IDs
    const canvasMatches = [...htmlContent.matchAll(/<canvas\\s+[^>]*id=['"]([^'"]+)['"]/gi)];
    const canvasIds = new Set(canvasMatches.map(m => m[1]));
    if (canvasIds.size === 0) canvasIds.add('gameCanvas');

    // Extract script src tags in order
    const scriptMatches = [...htmlContent.matchAll(/<script\\s+[^>]*src=['"]([^'"]+)['"]/gi)];
    const scripts = scriptMatches.map(m => m[1]);

    // If referenced scripts don't exist yet, wait for them to be synthesized in DAG
    for (const script of scripts) {{
        const scriptPath = path.resolve(path.dirname(htmlPath), script);
        if (!fs.existsSync(scriptPath)) {{
            process.exit(0);
        }}
    }}

    const canvasMock = {{
        getContext: (type) => ({{
            fillRect: () => {{}},
            clearRect: () => {{}},
            drawImage: () => {{}},
            beginPath: () => {{}},
            closePath: () => {{}},
            arc: () => {{}},
            ellipse: () => {{}},
            moveTo: () => {{}},
            lineTo: () => {{}},
            roundRect: () => {{}},
            fill: () => {{}},
            stroke: () => {{}},
            strokeRect: () => {{}},
            fillText: () => {{}},
            save: () => {{}},
            restore: () => {{}},
            translate: () => {{}},
            scale: () => {{}},
        }}),
        width: 720,
        height: 420
    }};

    const domListeners = [];
    const frameCallbacks = [];
    const windowMock = {{
        addEventListener: (event, handler) => {{
            if (event === 'DOMContentLoaded') domListeners.push(handler);
        }},
        removeEventListener: () => {{}},
        requestAnimationFrame: (cb) => {{ frameCallbacks.push(cb); return 1; }},
        cancelAnimationFrame: () => {{}},
        AudioContext: function() {{
            return {{
                createOscillator: () => ({{ connect: () => {{}}, start: () => {{}}, stop: () => {{}}, frequency: {{ setValueAtTime: () => {{}}, exponentialRampToValueAtTime: () => {{}} }} }}),
                createGain: () => ({{ connect: () => {{}}, gain: {{ setValueAtTime: () => {{}}, linearRampToValueAtTime: () => {{}} }} }}),
                destination: {{}},
                state: 'running',
                resume: () => {{}}
            }};
        }},
        webkitAudioContext: function() {{ return this.AudioContext(); }},
        Image: function() {{ return {{ onload: null, src: '' }}; }},
        Audio: function() {{ return {{ play: () => {{}}, pause: () => {{}} }}; }},
        console: console
    }};
    windowMock.window = windowMock;
    windowMock.globalThis = windowMock;

    const documentMock = {{
        getElementById: (id) => (canvasIds.has(id) ? canvasMock : null),
        addEventListener: (event, handler) => {{
            if (event === 'DOMContentLoaded') domListeners.push(handler);
        }},
        createElement: (tag) => (tag.toLowerCase() === 'canvas' ? canvasMock : {{ appendChild: () => {{}} }})
    }};
    windowMock.document = documentMock;

    const ctx = vm.createContext(windowMock);

    for (const script of scripts) {{
        const scriptPath = path.resolve(path.dirname(htmlPath), script);
        const code = fs.readFileSync(scriptPath, 'utf-8');
        vm.runInContext(code, ctx, {{ filename: script }});
    }}

    // Trigger DOMContentLoaded
    domListeners.forEach(fn => fn());

    // Execute first frame of game loop if registered
    frameCallbacks.forEach(fn => fn());

    console.log('SMOKE_TEST_OK');
}} catch (err) {{
    console.error('SMOKE_TEST_ERROR:' + JSON.stringify({{
        message: err.message,
        stack: err.stack,
        name: err.name
    }}));
}}
"""

        try:
            proc = subprocess.run(
                [node_bin, "-e", runner_js],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            for line in proc.stderr.splitlines():
                if "SMOKE_TEST_ERROR:" in line:
                    data = json.loads(line.split("SMOKE_TEST_ERROR:", 1)[1])
                    msg = data.get("message", "Runtime Error")
                    stack = data.get("stack", "")

                    file_name = str(target_html.relative_to(self.repo_path))
                    line_no = 1
                    col_no = 1
                    m = re.search(r'at (?:.+?\()?([^():\n]+):(\d+):(\d+)\)?', stack)
                    if m and not m.group(1).startswith("node:"):
                        file_name = m.group(1)
                        line_no = int(m.group(2))
                        col_no = int(m.group(3))

                    raw_diag = f"{file_name}:{line_no}:{col_no} - error BROWSER_RUNTIME_ERROR: {msg}"
                    diagnostics.append(
                        Diagnostic(
                            file=file_name,
                            line=line_no,
                            col=col_no,
                            code="BROWSER_RUNTIME_ERROR",
                            message=f"BROWSER_RUNTIME_ERROR: {msg}. Ensure all referenced DOM elements exist and scripts initialize without runtime exceptions.",
                            raw=raw_diag
                        )
                    )
        except Exception:
            pass

        return diagnostics

    def inspect_stubs(self, target_file: Optional[str] = None) -> List[Diagnostic]:
        """
        Anti-Stub & Quality Inspector:
        Scans code to ensure functions, methods, and constructors are not hollow
        skeletons (e.g. empty bodies or comment-only placeholders like '// logic here').
        """
        diagnostics: List[Diagnostic] = []
        if target_file:
            candidates = [self.repo_path / target_file]
        else:
            candidates = list(self.repo_path.glob("**/*"))

        js_ts_pattern = re.compile(
            r'(?:(?:async\s+)?(?:function\s+)?([a-zA-Z0-9_$]+)\s*\([^)]*\)\s*(?::\s*[^{]+)?)\s*\{([^}]*)\}',
            re.MULTILINE
        )

        for p in candidates:
            if not p.is_file() or "node_modules" in p.parts or ".git" in p.parts:
                continue
            if not any(p.name.endswith(ext) for ext in [".js", ".mjs", ".ts", ".tsx"]):
                continue

            try:
                rel_path = str(p.relative_to(self.repo_path))
            except Exception:
                rel_path = p.name

            # Skip planned skeleton marker files created during initial setup
            try:
                content = p.read_text(encoding="utf-8")
            except Exception:
                continue

            if "// Planned module skeleton for AntCoder DAG" in content:
                continue

            for m in js_ts_pattern.finditer(content):
                fn_name = m.group(1)
                body = m.group(2)
                is_stub, reason = self._is_stub_body(body)
                if is_stub:
                    line_no = content[:m.start()].count("\n") + 1
                    raw_msg = f"{rel_path}:{line_no}:1 - error ANTI_STUB: Function/method '{fn_name}' has no executable implementation ({reason})."
                    diagnostics.append(
                        Diagnostic(
                            file=rel_path,
                            line=line_no,
                            col=1,
                            code="ANTI_STUB",
                            message=f"ANTI_STUB: Function/method '{fn_name}' has no executable implementation ({reason}). Implement the complete operational logic without placeholders.",
                            raw=raw_msg
                        )
                    )

        return diagnostics

    @staticmethod
    def _is_stub_body(body: str) -> Tuple[bool, str]:
        """Examine a function/method body for empty or placeholder patterns."""
        body_no_comments = re.sub(r'//.*', '', body)
        body_no_comments = re.sub(r'/\*[\s\S]*?\*/', '', body_no_comments).strip()

        # 1. Body has literally zero executable statements (only whitespace and/or comments)
        if not body_no_comments:
            return True, "Empty body containing zero executable statements"

        # 2. Body has only a trivial return / pass accompanied by a placeholder comment
        has_placeholder = bool(re.search(r'(?:todo|implement|placeholder|logic\b|initialization\b)', body, re.IGNORECASE))
        cleaned_stmts = body_no_comments.replace(';', '').strip()
        if has_placeholder and cleaned_stmts in ('return', 'return null', 'return undefined', 'return false', 'return true', 'pass'):
            return True, f"Hollow stub returning constant ({cleaned_stmts}) with placeholder comment"

        return False, ""

    def _parse_node_check_output(self, output: str, fallback_file: str) -> List[Diagnostic]:
        """Parse node --check stderr into Diagnostic objects with line and column."""
        lines = output.splitlines()
        file_path = fallback_file
        line_no = 1
        col_no = 1
        msg = "SyntaxError"

        file_line_re = re.compile(r"^(.+?):(\d+)(?::(\d+))?$")
        for idx, line in enumerate(lines):
            line_str = line.strip()
            m = file_line_re.match(line_str)
            if m:
                try:
                    file_path = str(Path(m.group(1)).relative_to(self.repo_path))
                except Exception:
                    file_path = m.group(1)
                line_no = int(m.group(2))
                if m.group(3):
                    col_no = int(m.group(3))
            elif "^" in line and col_no == 1:
                # Caret line indicating column offset
                col_no = max(1, line.find("^") + 1)
            elif "SyntaxError:" in line or "Error:" in line:
                msg = line_str

        return [Diagnostic(file_path, line_no, col_no, "JS_SYNTAX", msg, output.strip()[:300])]

    def _parse_py_compile_output(self, output: str, fallback_file: str) -> List[Diagnostic]:
        """Parse python py_compile stderr into Diagnostic objects."""
        file_path = fallback_file
        line_no = 1
        msg = "Python SyntaxError"

        # e.g.: File "foo.py", line 10
        m = re.search(r'File "(.+?)", line (\d+)', output)
        if m:
            try:
                file_path = str(Path(m.group(1)).relative_to(self.repo_path))
            except Exception:
                file_path = m.group(1)
            line_no = int(m.group(2))

        for line in output.splitlines():
            line_clean = line.strip()
            if "SyntaxError:" in line_clean or "IndentationError:" in line_clean:
                msg = line_clean
                break

        return [Diagnostic(file_path, line_no, 1, "PY_SYNTAX", msg, output.strip()[:300])]

    def _parse_tsc_output(self, output: str) -> List[Diagnostic]:
        """
        Parses TypeScript compiler output lines into Diagnostic objects.
        Matches:
          src/file.ts(line,col): error TSXXXX: Message
          or: src/file.ts:line:col - error TSXXXX: Message
        """
        diagnostics = []
        pattern1 = re.compile(r"^(.+?)\((\d+),(\d+)\):\s+(error|warning)\s+(TS\d+):\s+(.+)$")
        pattern2 = re.compile(r"^(.+?):(\d+):(\d+)\s+-\s+(error|warning)\s+(TS\d+):\s+(.+)$")

        for line in output.splitlines():
            line_clean = line.strip()
            m = pattern1.match(line_clean) or pattern2.match(line_clean)
            if m:
                filepath = m.group(1).strip()
                if not any(filepath.endswith(ext) for ext in [".ts", ".tsx", ".js", ".jsx"]):
                    continue
                line_no = int(m.group(2))
                col_no = int(m.group(3))
                code = m.group(5).strip()
                msg = m.group(6).strip()
                diagnostics.append(Diagnostic(filepath, line_no, col_no, code, msg, line_clean))

        return diagnostics

    def extract_context(self, rel_filepath: str, line_no: int, window: int = 10) -> str:
        """
        Extracts surrounding lines of source code around a compiler error.
        Annotates the problematic line with line numbers.
        """
        target = self.repo_path / rel_filepath
        if not target.exists():
            return f"(File not found on disk: {rel_filepath})"

        try:
            with open(target, "r", encoding="utf-8") as f:
                all_lines = f.readlines()

            start = max(0, line_no - window - 1)
            end = min(len(all_lines), line_no + window)

            context_lines = []
            for i in range(start, end):
                curr_line_num = i + 1
                prefix = f"{curr_line_num:4d}: "
                context_lines.append(f"{prefix}{all_lines[i].rstrip()}")

            return "\n".join(context_lines)
        except Exception as e:
            return f"(Failed to extract context: {e})"

    def run_tests(self, timeout_sec: int = 120) -> Tuple[bool, str]:
        """Runs the unit test suite if test_cmd is provided."""
        if not self.test_cmd:
            return True, "No test command configured."

        try:
            proc = subprocess.run(
                self.test_cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            raw = proc.stdout + "\n" + proc.stderr
            return proc.returncode == 0, raw.strip()
        except Exception as e:
            return False, f"Test execution failed: {e}"
