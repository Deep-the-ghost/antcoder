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
        if (self.repo_path / "tsconfig.build.json").exists():
            return ["npx", "--no-install", "tsc", "--noEmit", "-p", "tsconfig.build.json"]
        elif (self.repo_path / "tsconfig.json").exists():
            return ["npx", "--no-install", "tsc", "--noEmit"]
        return ["npx", "tsc", "--noEmit"]

    def run_compiler(self, timeout_sec: int = 60) -> Tuple[bool, List[Diagnostic], str]:
        """
        Runs the TypeScript compiler.
        Returns: (success: bool, diagnostics: List[Diagnostic], raw_output: str)
        """
        try:
            proc = subprocess.run(
                self.build_cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            raw = proc.stdout + "\n" + proc.stderr
            if proc.returncode == 0:
                return True, [], raw.strip()

            diagnostics = self._parse_tsc_output(raw)
            return False, diagnostics, raw.strip()
        except subprocess.TimeoutExpired:
            return False, [], "Compiler execution timed out."
        except Exception as e:
            return False, [], f"Compiler execution error: {str(e)}"

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
