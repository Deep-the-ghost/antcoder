"""
Rich Terminal User Interface for Ant Coder
Provides animated spinners, styled panels, live DAG progress trees,
and beautiful ANSI colored output.
"""

import sys
import time

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.tree import Tree
    from rich.table import Table
    from rich.text import Text
    from rich.progress import Progress, SpinnerColumn, TextColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class TerminalUI:
    def __init__(self):
        self.rich = RICH_AVAILABLE
        if self.rich:
            self.console = Console()
        else:
            self.console = None

    def print_banner(self):
        banner = """
    █████╗ ███╗   ██╗████████╗     ██████╗ ██████╗ ██████╗ ███████╗██████╗ 
   ██╔══██╗████╗  ██║╚══██╔══╝    ██╔════╝██╔═══██╗██╔══██╗██╔════╝██╔══██╗
   ███████║██╔██╗ ██║   ██║       ██║     ██║   ██║██║  ██║█████╗  ██████╔╝
   ██╔══██║██║╚██╗██║   ██║       ██║     ██║   ██║██║  ██║██╔══╝  ██╔══██╗
   ██║  ██║██║ ╚████║   ██║       ╚██████╗╚██████╔╝██████╔╝███████╗██║  ██║
   ╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝        ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
        """
        subtitle = "Autonomous Sub-8B Multi-Agent Software Engineering CLI • v0.1.0"
        
        if self.rich:
            self.console.print(f"[bold cyan]{banner}[/bold cyan]")
            self.console.print(Panel(
                f"[bold white]{subtitle}[/bold white]\n[dim]Architected by Deep Das • Powered by Qwen2.5-Coder-7B LoRA Suite[/dim]",
                border_style="bright_blue",
                expand=False
            ))
        else:
            print(f"\033[1;36m{banner}\033[0m")
            print(f"\033[1;37m{subtitle}\033[0m\n")

    def print_goal(self, goal: str, repo: str):
        if self.rich:
            t = Table(show_header=False, box=None)
            t.add_row("[bold cyan]Target Repo:[/bold cyan]", f"[white]{repo}[/white]")
            t.add_row("[bold cyan]Feature Goal:[/bold cyan]", f"[bold yellow]\"{goal}\"[/bold yellow]")
            self.console.print(Panel(t, title="[bold]Autonomous Session Configuration[/bold]", border_style="cyan"))
        else:
            print(f"\033[1;36m[TARGET REPO]\033[0m {repo}")
            print(f"\033[1;33m[FEATURE GOAL]\033[0m \"{goal}\"\n")

    def print_dag(self, dag: list, order: tuple):
        if self.rich:
            tree = Tree("🗺️ [bold magenta]Architectural Dependency DAG[/bold magenta]")
            for task_id in order:
                task = next((t for t in dag if t["id"] == task_id), None)
                if task:
                    deps = task.get("deps") or []
                    dep_str = f" [dim](depends on: {', '.join(deps)})[/dim]" if deps else ""
                    tree.add(f"[bold green]Node:[/bold green] [bold white]{task_id}[/bold white] ➔ [cyan]{task['file']}[/cyan]{dep_str}")
            self.console.print(tree)
            self.console.print()
        else:
            print("=== ARCHITECTURAL DAG ===")
            for task_id in order:
                print(f" -> {task_id}")
            print()

    def handle_event(self, event: str, data: dict):
        if self.rich:
            if event == "branch_created":
                self.console.print(f"🌿 [dim]Isolated workspace branch:[/dim] [bold green]{data['branch']}[/bold green]")
            elif event == "planner_start":
                self.console.print("🗺️  [bold magenta]AntCoder-Planner-7B[/bold magenta] decomposing requirements into DAG...")
            elif event == "planner_complete":
                self.console.print(f"✅ [bold green]Planner decomposed into {len(data['dag'])} modular tasks.[/bold green]")
                self.print_dag(data['dag'], data['order'])
            elif event == "task_start":
                self.console.print(f"\n🏗️  [bold blue]AntCoder-Builder-7B[/bold blue] [{data['index']}/{data['total']}] synthesizing [bold cyan]{data['file']}[/bold cyan]...")
            elif event == "builder_complete":
                self.console.print(f"   [dim]Synthesized {data['lines']} lines of zero-stub TypeScript. Running compiler...[/dim]")
            elif event == "verifier_pass":
                self.console.print("   ✅ [bold green]Typecheck passed cleanly (0 errors)![/bold green]")
            elif event == "verifier_fail":
                self.console.print(f"   ⚠️  [bold yellow]Compiler caught {data['errors']} diagnostic(s). Invoking AntCoder-Fixer-7B...[/bold yellow]")
            elif event == "fixer_start":
                self.console.print(f"   🛠️  [bold red]AntCoder-Fixer-7B[/bold red] generating surgical unified diff [attempt {data['attempt']}/{data['max']}]...")
            elif event == "fixer_patch_applied":
                self.console.print("   🔄 [dim]Applied git diff patch. Re-verifying compiler...[/dim]")
            elif event == "fixer_resolved":
                self.console.print(f"   🎉 [bold green]Compiler error resolved on attempt {data['attempt']}![/bold green]")
            elif event == "feature_complete":
                self.console.print(Panel(
                    f"[bold green]✨ FEATURE IMPLEMENTED & VERIFIED WITH 0 COMPILER ERRORS![/bold green]\n\n"
                    f"[bold white]Branch:[/bold white] [cyan]{data['branch']}[/cyan]\n"
                    f"[bold white]Commit:[/bold white] [dim]{data['commit'][:80]}...[/dim]\n\n"
                    f"Merge into main via:\n[bold yellow]git merge {data['branch']}[/bold yellow]",
                    title="[bold green]Success[/bold green]",
                    border_style="green"
                ))
            elif event == "task_failed":
                self.console.print(f"\n❌ [bold red]Task Verification Failed:[/bold red] Task [cyan]{data.get('task_id')}[/cyan] ({data.get('file')}) has [bold red]{data.get('errors')}[/bold red] unresolved diagnostic(s):")
                for d in data.get("diagnostics", []):
                    line = d.get("line", "?")
                    msg = d.get("message", d.get("raw", ""))
                    code = d.get("code", "ERROR")
                    self.console.print(f"   🔴 [bold yellow]Line {line}[/bold yellow] [{code}]: {msg}")
                self.console.print("   🔄 [dim]Strict verification gate triggered: rolling back workspace.[/dim]")
            elif event == "task_abort":
                self.console.print(f"\n❌ [bold red]Task aborted:[/bold red] {data.get('reason')}. Atomic rollback executed.")
            elif event == "fatal_error":
                self.console.print(f"\n🚨 [bold red]Fatal Engine Error:[/bold red] {data.get('error')}. Rollback executed.")
        else:
            print(f"[{time.strftime('%H:%M:%S')}] {event.upper()}: {data}")
