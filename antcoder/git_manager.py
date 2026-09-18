"""
Git Workspace Isolation & Version Control Manager
Handles feature branches, diff application, rollbacks, and atomic commits.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple


class GitManager:
    def __init__(self, repo_path: Path):
        self.repo_path = Path(repo_path).resolve()
        if not (self.repo_path / ".git").exists():
            raise ValueError(f"Not a valid git repository: {self.repo_path}")

    def _run(self, cmd: list, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=check,
        )

    def get_current_branch(self) -> str:
        try:
            res = self._run(["git", "symbolic-ref", "--short", "HEAD"], check=False)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
            res = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=False)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return "main"

    def create_feature_branch(self, branch_name: str) -> bool:
        """Create and checkout a new branch for the agent's work."""
        # Check if repo has any commits; if empty, initialize with an initial commit
        has_commits = self._run(["git", "rev-parse", "--verify", "HEAD"], check=False).returncode == 0
        if not has_commits:
            try:
                self._run(["git", "commit", "--allow-empty", "-m", "chore: initialize repository"], check=False)
            except Exception:
                pass

        try:
            self._run(["git", "checkout", "-b", branch_name])
            return True
        except subprocess.CalledProcessError:
            self._run(["git", "checkout", branch_name], check=False)
            return False

    def rollback(self) -> None:
        """Discard all uncommitted modifications atomically."""
        self._run(["git", "checkout", "--", "."])
        self._run(["git", "clean", "-fd"])

    def get_diff(self) -> str:
        """Get the current uncommitted git diff."""
        res = self._run(["git", "diff"], check=False)
        return res.stdout

    def commit(self, message: str) -> Tuple[bool, str]:
        """Stage all changes and commit with metadata."""
        try:
            self._run(["git", "add", "-A"])
            res = self._run(["git", "commit", "-m", message])
            return True, res.stdout.strip()
        except subprocess.CalledProcessError as e:
            return False, e.stderr.strip()

    def apply_patch(self, diff_content: str) -> Tuple[bool, str]:
        """
        Applies a unified diff patch.
        Uses `git apply` with whitespace flexibility and falls back to manual hunk replacement.
        """
        clean_diff = diff_content.strip()
        if clean_diff.startswith("```diff"):
            clean_diff = clean_diff[len("```diff"):].strip()
        if clean_diff.startswith("```"):
            clean_diff = clean_diff[len("```"):].strip()
        if clean_diff.endswith("```"):
            clean_diff = clean_diff[:-3].strip()

        # Try 1: Standard git apply with zero unidiff tolerance
        proc = subprocess.run(
            ["git", "apply", "--whitespace=fix", "--unidiff-zero", "-"],
            input=clean_diff,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return True, "Patch applied cleanly via git apply."

        # Try 2: Git apply with whitespace ignoring
        proc2 = subprocess.run(
            ["git", "apply", "--ignore-space-change", "--ignore-whitespace", "-"],
            input=clean_diff,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        if proc2.returncode == 0:
            return True, "Patch applied with whitespace tolerance."

        # Try 3: Fallback manual AST/text hunk replacer
        success, msg = self._manual_apply_diff(clean_diff)
        if success:
            return True, f"Patch applied via fallback hunk replacer: {msg}"

        return False, f"Git apply failed: {proc.stderr}\nFallback: {msg}"

    def _manual_apply_diff(self, diff_text: str) -> Tuple[bool, str]:
        lines = diff_text.splitlines()
        target_file = None
        
        for line in lines:
            if line.startswith("+++ b/"):
                target_file = line[6:].strip()
                break
            elif line.startswith("+++ "):
                target_file = line[4:].strip().lstrip("b/").lstrip("a/")
                break

        if not target_file:
            return False, "Could not determine target file from diff header."

        abs_file = self.repo_path / target_file
        if not abs_file.exists():
            return False, f"Target file does not exist: {target_file}"

        with open(abs_file, "r", encoding="utf-8") as f:
            content = f.read()

        removals = []
        additions = []
        for line in lines:
            if line.startswith("-") and not line.startswith("---"):
                removals.append(line[1:])
            elif line.startswith("+") and not line.startswith("+++"):
                additions.append(line[1:])

        old_block = "\n".join(removals)
        new_block = "\n".join(additions)

        if old_block and old_block in content:
            updated_content = content.replace(old_block, new_block, 1)
            with open(abs_file, "w", encoding="utf-8") as f:
                f.write(updated_content)
            return True, f"Replaced target block in {target_file}"

        return False, "Could not locate matching target block for replacement."
