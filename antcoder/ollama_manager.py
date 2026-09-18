"""
Ollama Lifecycle & Autonomous Model Provisioner for Ant Coder
============================================================
Handles automatic Ollama server verification, base model pulling,
and instant creation of the Tri-Agent roles:
  - antcoder-planner
  - antcoder-builder
  - antcoder-fixer
"""

import json
import time
import shutil
import subprocess
import urllib.request
import urllib.error
from typing import Tuple, Dict, Any, Optional

OLLAMA_HOST = "http://localhost:11434"
DEFAULT_BASE_MODEL = "qwen2.5-coder:7b"
FALLBACK_BASE_MODEL = "qwen2.5:7b-instruct"

PLANNER_SYSTEM_PROMPT = (
    "You are AntCoder Planner, an autonomous software engineering architect. "
    "Decompose high-level feature requests into a topologically sortable JSON DAG adhering to "
    "enterprise scalability invariants (layered decoupling, bounded cursor pagination <=50, "
    "atomic database transaction scopes, and Zod runtime schema boundaries). "
    "Output ONLY valid JSON."
)

BUILDER_SYSTEM_PROMPT = (
    "You are AntCoder Builder, an autonomous software engineering implementation engine. "
    "Synthesize complete, strictly-typed, 100% zero-stub production TypeScript implementations "
    "from contracts, interfaces, or method signatures. "
    "Never use lazy stubs, TODO comments, or placeholder throws. Output ONLY the TypeScript code block."
)

FIXER_SYSTEM_PROMPT = (
    "You are AntCoder Fixer, an automated compiler diagnostic repair engine. "
    "Given a TypeScript compiler diagnostic error (tsc) and source context, "
    "synthesize a minimal, surgical Git Unified Diff patch. "
    "Output ONLY standard Git Unified Diff syntax (--- a/... +++ b/... @@ ... @@)."
)


class OllamaManager:
    def __init__(self, host: str = OLLAMA_HOST):
        self.host = host.rstrip("/")

    def is_server_running(self) -> bool:
        """Check if Ollama HTTP server is responsive."""
        try:
            req = urllib.request.Request(f"{self.host}/api/tags", headers={"User-Agent": "AntCoder"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def start_server_if_needed(self, ui=None) -> bool:
        """Start Ollama background process if it is not already running."""
        if self.is_server_running():
            return True

        ollama_bin = shutil.which("ollama") or "/snap/bin/ollama"
        if not shutil.which(ollama_bin):
            return False

        if ui and ui.rich:
            ui.console.print("[dim]⚡ Starting local Ollama server...[/dim]")
        elif ui:
            print("⚡ Starting local Ollama server...")

        try:
            subprocess.Popen(
                [ollama_bin, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            # Wait up to 10 seconds for server to start
            for _ in range(20):
                time.sleep(0.5)
                if self.is_server_running():
                    return True
        except Exception:
            return False

        return False

    def list_models(self) -> list:
        """List all installed models in Ollama."""
        try:
            req = urllib.request.Request(f"{self.host}/api/tags", headers={"User-Agent": "AntCoder"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []

    def pull_model(self, model_name: str, ui=None) -> bool:
        """Pull a model via Ollama API with streaming progress."""
        if ui and ui.rich:
            ui.console.print(f"[bold cyan]📥 Pulling '{model_name}' into Ollama (this runs once)...[/bold cyan]")
        elif ui:
            print(f"📥 Pulling '{model_name}' into Ollama...")

        try:
            url = f"{self.host}/api/pull"
            payload = json.dumps({"name": model_name, "stream": False}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as resp:
                return resp.status == 200
        except Exception as e:
            if ui and ui.rich:
                ui.console.print(f"[red]Failed to pull {model_name}: {e}[/red]")
            return False

    def create_role_model(self, role_name: str, base_model: str, system_prompt: str) -> bool:
        """Create a specialized model role in Ollama with system instructions and parameters."""
        try:
            url = f"{self.host}/api/create"
            payload = json.dumps({
                "model": role_name,
                "from": base_model,
                "system": system_prompt,
                "stream": False
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status == 200
        except Exception:
            return False

    def setup_antcoder_suite(self, ui=None) -> Tuple[bool, str, Dict[str, str]]:
        """
        End-to-end setup:
        1. Start server
        2. Detect / Pull base model
        3. Provision antcoder-planner, antcoder-builder, antcoder-fixer
        Returns: (success, endpoint_v1, model_dict)
        """
        if not self.start_server_if_needed(ui):
            return False, "", {}

        installed = self.list_models()
        # Find best available base model
        base_model = None
        for candidate in [DEFAULT_BASE_MODEL, "qwen2.5-coder:latest", FALLBACK_BASE_MODEL, "qwen2.5:latest"]:
            for m in installed:
                if candidate in m or m.startswith(candidate.split(":")[0]):
                    base_model = m
                    break
            if base_model:
                break

        if not base_model:
            # Pull default base model
            if self.pull_model(DEFAULT_BASE_MODEL, ui):
                base_model = DEFAULT_BASE_MODEL
            else:
                return False, "", {}

        # Ensure Tri-Agent models exist
        roles = {
            "planner": ("antcoder-planner", PLANNER_SYSTEM_PROMPT),
            "builder": ("antcoder-builder", BUILDER_SYSTEM_PROMPT),
            "fixer": ("antcoder-fixer", FIXER_SYSTEM_PROMPT),
        }

        configured_models = {}
        for role_key, (role_name, sys_prompt) in roles.items():
            found = any(role_name in m for m in installed)
            if not found:
                if ui and ui.rich:
                    ui.console.print(f"[dim]⚙️ Provisioning {role_name} on top of {base_model}...[/dim]")
                self.create_role_model(role_name, base_model, sys_prompt)
            configured_models[role_key] = role_name

        v1_endpoint = f"{self.host}/v1"
        return True, v1_endpoint, configured_models
