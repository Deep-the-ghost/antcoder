"""
Universal Model Inference Client:
Interfaces with local vLLM / Ollama servers (supporting dynamic LoRA switching),
direct local PEFT / HuggingFace models, and provides a Mock client for deterministic testing.
"""

import json
import urllib.request
import urllib.error
from typing import List, Dict, Optional


class BaseModelClient:
    def query(self, messages: List[Dict[str, str]], model_type: str = "builder") -> str:
        raise NotImplementedError


class HTTPModelClient(BaseModelClient):
    """
    Connects to an OpenAI-compatible endpoint (vLLM, Ollama, LMDeploy, or TGI).
    Supports hot-swapping adapters via the model field.
    """
    def __init__(
        self,
        base_url: str = "http://localhost:8000/v1",
        api_key: str = "none",
        planner_model: str = "planner_lora",
        builder_model: str = "builder_lora",
        fixer_model: str = "fixer_lora"
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.planner_model = planner_model
        self.builder_model = builder_model
        self.fixer_model = fixer_model

    def query(self, messages: List[Dict[str, str]], model_type: str = "builder") -> str:
        if model_type == "planner":
            target_model = self.planner_model
        elif model_type == "fixer":
            target_model = self.fixer_model
        else:
            target_model = self.builder_model

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 2048,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except urllib.error.URLError as e:
            raise ConnectionError(f"Failed to communicate with LLM server at {url}: {e}")


class MockModelClient(BaseModelClient):
    """
    Deterministic Simulator for validating the full Planner -> Builder -> Fixer scaffolding.
    """
    def __init__(
        self,
        planner_response: Optional[str] = None,
        builder_response: Optional[str] = None,
        fixer_response: Optional[str] = None,
        builder_fn=None,
        fixer_fn=None,
    ):
        self.planner_response = planner_response
        self.builder_response = builder_response
        self.fixer_response = fixer_response
        self.builder_fn = builder_fn
        self.fixer_fn = fixer_fn
        self.query_history = []

    def query(self, messages: List[Dict[str, str]], model_type: str = "builder") -> str:
        self.query_history.append({"type": model_type, "messages": messages})
        if model_type == "planner":
            if self.planner_response:
                return self.planner_response
            return json.dumps({
                "feature": "sample_feature",
                "dag": [
                    {
                        "id": "types",
                        "file": "src/sample/types.ts",
                        "contract": "export interface SampleConfig { id: string; enabled: boolean; }",
                        "deps": []
                    },
                    {
                        "id": "service",
                        "file": "src/sample/service.ts",
                        "contract": "import { SampleConfig } from './types';\nexport function createService(cfg: SampleConfig) { return { active: cfg.enabled }; }",
                        "deps": ["types"]
                    }
                ]
            })
        elif model_type == "builder":
            if self.builder_fn:
                return self.builder_fn(messages)
            return self.builder_response or "// Mock Builder Implementation\nexport function mockFunc() { return true; }"
        elif model_type == "fixer":
            if self.fixer_fn:
                return self.fixer_fn(messages)
            return self.fixer_response or "```diff\n--- file.ts\n+++ file.ts\n@@ -1,1 +1,1 @@\n-// old\n+// fixed\n```"
        return ""
