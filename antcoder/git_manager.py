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
        self._run(["git", "checkout", "--", "."], check=False)
        self._run(["git", "clean", "-fd"], check=False)

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

    def apply_patch(self, patch_content: str, fallback_file: Optional[str] = None) -> Tuple[bool, str]:
        """
        Multi-Strategy Resilient Patch Engine:
        Strategy 1: Search-and-Replace Blocks (<<<<<<< SEARCH ... ======= ... >>>>>>>)
        Strategy 2: Context-Aware Hunk Parsing (header-independent diff replacement)
        Strategy 3: Standard Git Apply (with whitespace tolerance)
        Strategy 4: Full-File Code Block Replacement
        """
        clean_patch = patch_content.strip()

        # Strategy 1: Search-and-Replace Blocks
        if "<<<<<<< SEARCH" in clean_patch and "=======" in clean_patch:
            applied, msg = self._apply_search_replace_block(clean_patch, fallback_file)
            if applied:
                return True, f"Search/Replace applied: {msg}"

        # Strip markdown fences for diff / code
        stripped = clean_patch
        for prefix in ["```diff", "```patch", "```javascript", "```typescript", "```html", "```python", "```"]:
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):].strip()
        if stripped.endswith("```"):
            stripped = stripped[:-3].strip()

        # Strategy 2: Context-Aware Hunk Parsing
        if ("--- " in stripped or "+++ " in stripped) and "@@" in stripped:
            hunk_ok, hunk_msg = self._apply_context_hunk(stripped, fallback_file)
            if hunk_ok:
                return True, f"Context hunk applied: {hunk_msg}"

        # Strategy 3: Standard Git Apply
        proc = subprocess.run(
            ["git", "apply", "--whitespace=fix", "--unidiff-zero", "-"],
            input=stripped,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return True, "Patch applied cleanly via git apply."

        proc2 = subprocess.run(
            ["git", "apply", "--ignore-space-change", "--ignore-whitespace", "-"],
            input=stripped,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        if proc2.returncode == 0:
            return True, "Patch applied via git apply with whitespace tolerance."

        # Strategy 4: Full-File Replacement Fallback
        target_path = None
        if fallback_file:
            target_path = self.repo_path / fallback_file
        if target_path and target_path.exists() and not stripped.startswith("@@") and ("--- " not in stripped):
            try:
                target_path.write_text(stripped + "\n", encoding="utf-8")
                return True, f"Overwrote {fallback_file} with corrected code block."
            except Exception:
                pass

        return False, f"All patch strategies failed. Git apply error: {proc.stderr.strip()[:150]}"

    def _apply_search_replace_block(self, text: str, fallback_file: Optional[str] = None) -> Tuple[bool, str]:
        """Apply <<<<<<< SEARCH ... ======= ... >>>>>>> blocks."""
        pattern = re.compile(r'<<<<<<< SEARCH\s*\n(.*?)\n?=======\s*\n(.*?)\n?>>>>>>>', re.DOTALL)
        matches = list(pattern.finditer(text))
        if not matches:
            return False, "No valid SEARCH/REPLACE blocks found."

        # Detect target file from path comments e.g. // FILE: bird.js or fallback
        target_file = fallback_file
        file_m = re.search(r'(?:FILE|PATH):\s*([^\n\r]+)', text, re.IGNORECASE)
        if file_m:
            target_file = file_m.group(1).strip()

        if not target_file:
            return False, "Target file could not be determined for SEARCH/REPLACE."

        abs_file = self.repo_path / target_file
        if not abs_file.exists():
            return False, f"Target file does not exist: {target_file}"

        content = abs_file.read_text(encoding="utf-8")
        applied_count = 0

        for m in matches:
            search_part = m.group(1)
            replace_part = m.group(2)
            if search_part in content:
                content = content.replace(search_part, replace_part, 1)
                applied_count += 1
            else:
                # Try normalized whitespace search
                search_normalized = "\n".join(l.strip() for l in search_part.splitlines())
                content_lines = content.splitlines()
                # Find matching window
                sw_len = len(search_part.splitlines())
                for i in range(len(content_lines) - sw_len + 1):
                    window = "\n".join(l.strip() for l in content_lines[i:i + sw_len])
                    if window == search_normalized:
                        content_lines[i:i + sw_len] = replace_part.splitlines()
                        content = "\n".join(content_lines)
                        applied_count += 1
                        break

        if applied_count > 0:
            abs_file.write_text(content, encoding="utf-8")
            return True, f"Successfully applied {applied_count} search/replace block(s) in {target_file}"

        return False, "Search block content not found in target file."

    def _apply_context_hunk(self, diff_text: str, fallback_file: Optional[str] = None) -> Tuple[bool, str]:
        """Header-independent context hunk replacement."""
        lines = diff_text.splitlines()
        target_file = fallback_file

        for line in lines:
            if line.startswith("+++ b/"):
                target_file = line[6:].strip()
                break
            elif line.startswith("+++ "):
                target_file = line[4:].strip().lstrip("b/").lstrip("a/")
                break

        if not target_file:
            return False, "Target file unknown."

        abs_file = self.repo_path / target_file
        if not abs_file.exists():
            return False, f"File {target_file} does not exist."

        content = abs_file.read_text(encoding="utf-8")
        old_lines = []
        new_lines = []
        in_hunk = False

        for line in lines:
            if line.startswith("@@"):
                in_hunk = True
                continue
            if in_hunk:
                if line.startswith("---") or line.startswith("+++"):
                    continue
                if line.startswith(" ") or line.startswith("-"):
                    old_lines.append(line[1:])
                if line.startswith(" ") or line.startswith("+"):
                    new_lines.append(line[1:])

        old_text = "\n".join(old_lines)
        new_text = "\n".join(new_lines)

        if old_text and old_text in content:
            updated = content.replace(old_text, new_text, 1)
            abs_file.write_text(updated, encoding="utf-8")
            return True, f"Successfully applied context hunk in {target_file}"

        return False, "Could not match context hunk uniquely in target file."
