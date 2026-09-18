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

    # Interactive onboarding if goal is not passed via CLI argument
    if not args.goal:
        if sys.stdin.isatty():
            try:
                from rich.prompt import Prompt
                if ui.rich:
                    ui.console.print("\n[bold green]🐜 Ant Coder Interactive Assistant[/bold green]")
                    ui.console.print("[dim]Enter your goal below to begin autonomous software development:[/dim]\n")
                    goal = Prompt.ask("[bold cyan]🎯 What feature would you like to build?[/bold cyan]")
                else:
                    goal = input("\n🎯 What feature would you like to build?: ")

                if not goal or not goal.strip():
                    if ui.rich:
                        ui.console.print("[yellow]No goal entered. Exiting Ant Coder.[/yellow]")
                    else:
                        print("No goal entered. Exiting Ant Coder.")
                    sys.exit(0)
                args.goal = goal.strip()
            except (KeyboardInterrupt, EOFError):
                print("\nAborted.")
                sys.exit(0)
        else:
            parser.print_help()
            sys.exit(1)

    repo_path = Path(args.repo).resolve()
    if not (repo_path / ".git").exists():
        if sys.stdin.isatty():
            try:
                from rich.prompt import Prompt, Confirm
                default_hono = Path("/home/deep/Startup guide/seed_repos/hono")
                default_val = str(default_hono) if default_hono.exists() else str(repo_path)
                if ui.rich:
                    ui.console.print(f"\n[yellow]⚠️ '{repo_path}' is not a git repository.[/yellow]")
                    entered = Prompt.ask(
                        "[bold cyan]📁 Enter target repository path[/bold cyan]",
                        default=default_val
                    )
                else:
                    entered = input(f"\n📁 Enter target repository path [{default_val}]: ") or default_val
                
                repo_path = Path(entered).expanduser().resolve()
                if not (repo_path / ".git").exists():
                    should_init = Confirm.ask(
                        f"[yellow]Directory '{repo_path}' is not a git repo. Initialize git repository here?[/yellow]",
                        default=True
                    ) if ui.rich else (input("Initialize git here? [Y/n]: ").strip().lower() != 'n')
                    
                    if should_init:
                        import subprocess
                        repo_path.mkdir(parents=True, exist_ok=True)
                        subprocess.run(["git", "init"], cwd=repo_path, check=True)
                        subprocess.run(["git", "commit", "--allow-empty", "-m", "chore: initial commit"], cwd=repo_path, check=True)
                    else:
                        sys.exit(1)
            except (KeyboardInterrupt, EOFError):
                print("\nAborted.")
                sys.exit(0)
        else:
            if ui.rich:
                ui.console.print(f"[bold red]Error:[/bold red] '{repo_path}' is not a valid git repository.")
            else:
                print(f"Error: '{repo_path}' is not a valid git repository.")
            sys.exit(1)

    # Detect if local LLM endpoint is active or offer mock mode
    if not args.mock:
        endpoint_online = False
        import urllib.request
        for test_url in [f"{args.endpoint}/models", "http://localhost:1234/v1/models", "http://localhost:8000/v1/models"]:
            try:
                req = urllib.request.Request(test_url, headers={"User-Agent": "AntCoder"})
                with urllib.request.urlopen(req, timeout=0.6) as resp:
                    if resp.status == 200:
                        endpoint_online = True
                        if "1234" in test_url:
                            args.endpoint = "http://localhost:1234/v1"
                        break
            except Exception:
                continue

        if not endpoint_online:
            if sys.stdin.isatty():
                try:
                    from rich.prompt import Confirm
                    if ui.rich:
                        ui.console.print("\n[yellow]💡 Local LLM server (vLLM / LM Studio) is not running on port 8000/1234.[/yellow]")
                        run_mock = Confirm.ask(
                            "[bold green]🚀 Run in offline Simulation/Demo mode to test the agent workflow?[/bold green]",
                            default=True
                        )
                    else:
                        run_mock = (input("Run in offline simulation mode? [Y/n]: ").strip().lower() != 'n')
                    if run_mock:
                        args.mock = True
                    else:
                        if ui.rich:
                            ui.console.print("[dim]Please start your local LLM server and try again.[/dim]")
                        else:
                            print("Please start your local LLM server and try again.")
                        sys.exit(1)
                except (KeyboardInterrupt, EOFError):
                    print("\nAborted.")
                    sys.exit(0)

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
