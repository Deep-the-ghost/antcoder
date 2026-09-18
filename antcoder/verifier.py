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
                        "strict": False,
                        "skipLibCheck": True,
                        "esModuleInterop": True,
                        "allowJs": True
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

        success = len(all_diags) == 0
        return success, all_diags, "\n---\n".join(filter(None, raw_outputs))

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
