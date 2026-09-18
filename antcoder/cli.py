"""
CLI Entrypoint for Ant Coder
Command-line interface to execute autonomous software development loops.
"""

import sys
import argparse
from pathlib import Path

from .ui import TerminalUI
from .engine import ScaffoldingEngine
from .model_client import HTTPModelClient, MockModelClient


def main():
    parser = argparse.ArgumentParser(
        prog="antcoder",
        description="Ant Coder: Autonomous Sub-8B Multi-Agent Software Engineering CLI"
    )
    parser.add_argument(
        "goal",
        nargs="?",
        default=None,
        help="Natural language goal or feature description (e.g. 'Add JWT auth middleware with token rotation')"
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Path to target git repository (default: current working directory)"
    )
    parser.add_argument(
        "--endpoint",
        default="http://localhost:8000/v1",
        help="Local LLM inference endpoint (vLLM, Ollama, or OpenAI-compatible server)"
    )
    parser.add_argument(
        "--planner-model",
        default="planner_lora",
        help="Planner model or LoRA adapter name (default: planner_lora)"
    )
    parser.add_argument(
        "--builder-model",
        default="builder_lora",
        help="Builder model or LoRA adapter name (default: builder_lora)"
    )
    parser.add_argument(
        "--fixer-model",
        default="fixer_lora",
        help="Fixer model or LoRA adapter name (default: fixer_lora)"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in simulated mode to test the deterministic multi-agent harness without a GPU server"
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Maximum compiler fixer loop retries per task (default: 3)"
    )

    args = parser.parse_args()

    ui = TerminalUI()
    ui.print_banner()

    if not args.goal:
        parser.print_help()
        sys.exit(1)

    repo_path = Path(args.repo).resolve()
    if not (repo_path / ".git").exists():
        if ui.rich:
            ui.console.print(f"[bold red]Error:[/bold red] '{repo_path}' is not a valid git repository.")
        else:
            print(f"Error: '{repo_path}' is not a valid git repository.")
        sys.exit(1)

    ui.print_goal(goal=args.goal, repo=str(repo_path))

    if args.mock:
        client = MockModelClient()
    else:
        client = HTTPModelClient(
            base_url=args.endpoint,
            planner_model=args.planner_model,
            builder_model=args.builder_model,
            fixer_model=args.fixer_model,
        )

    engine = ScaffoldingEngine(
        repo_path=repo_path,
        model_client=client,
        max_fix_retries=args.retries,
        event_callback=ui.handle_event,
    )

    result = engine.execute_feature_goal(
        goal_description=args.goal
    )

    if result.get("status") == "SUCCESS":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
