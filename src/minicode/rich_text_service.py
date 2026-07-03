"""
rich_text_service.py
---------------------
Every terminal-rendering concern in one file: the banner, the input
prompt, syntax highlighting, and the human-approval prompt. Nothing else
in the project touches `rich` directly -- if you ever want to change how
Mini Code LOOKS, this is the only file you need to open.
"""

import difflib
import os

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table

from minicode.constants import LOGO, MODEL

CONSOLE = Console()

# Extension -> Pygments lexer name, for syntax-highlighted diffs/previews.
EXT_TO_LEXER = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".json": "json", ".md": "markdown", ".html": "html", ".css": "css",
    ".sh": "bash", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
}


def guess_lexer(path: str) -> str:
    """Guess a Pygments lexer name from a file's extension."""
    ext = os.path.splitext(path)[1].lower()
    return EXT_TO_LEXER.get(ext, "text")


def print_banner(thread_id: str) -> None:
    """Shown once, at the start of a session: logo + session details."""
    CONSOLE.print(LOGO, style="bold cyan")

    info = Table.grid(padding=(0, 2))
    info.add_column(style="bold")
    info.add_column()
    info.add_row("Project Directory", os.getcwd())
    info.add_row("Session ID", thread_id)
    info.add_row("Model", MODEL)
    CONSOLE.print(Panel(info, border_style="cyan", title="Session", title_align="left"))

    CONSOLE.print("Type a task and press Enter. Type 'exit' or 'quit' to stop.\n", style="dim")


def read_task():
    """A bordered prompt line, then a plain input() beneath it."""
    CONSOLE.print(Rule(style="cyan"))
    try:
        task = CONSOLE.input("[bold cyan]>[/bold cyan] ")
    except KeyboardInterrupt:
        return None
    return task.strip()


def print_goodbye() -> None:
    CONSOLE.print("\nSession ended.", style="dim")


def print_assistant_text(text: str) -> None:
    """Print the assistant's streamed text, token by token."""
    CONSOLE.print(text, end="", markup=False, highlight=False)


def print_tool_call(name: str, args: dict) -> None:
    CONSOLE.print(f"\n→ {name}({args})", style="bold cyan", markup=False)


def print_tool_result(content: str) -> None:
    preview = content if len(content) < 1200 else content[:1200] + "\n... (truncated)"
    CONSOLE.print(preview, style="dim", markup=False)


def diff_preview(path: str, old_str: str, new_str: str):
    """A colored, syntax-highlighted unified diff, for edit_file's approval prompt."""
    diff_lines = difflib.unified_diff(
        old_str.splitlines(keepends=True),
        new_str.splitlines(keepends=True),
        fromfile=f"{path} (before)",
        tofile=f"{path} (after)",
    )
    diff_text = "".join(diff_lines)
    if not diff_text:
        return "(no visible line differences)"
    return Syntax(diff_text, "diff", theme="monokai", line_numbers=False, word_wrap=True)


def code_preview(path: str, content: str, max_chars: int = 2000):
    """A syntax-highlighted preview of new file content, for write_file's approval prompt."""
    preview_text = content if len(content) < max_chars else content[:max_chars] + "\n... (truncated)"
    return Syntax(preview_text, guess_lexer(path), theme="monokai", line_numbers=True, word_wrap=True)


def confirm(title: str, body) -> bool:
    """Ask the human to approve an action: a bordered panel with the
    diff/preview/warning inside, then a clean yes/no prompt."""
    CONSOLE.print()
    panel_body = body if not isinstance(body, str) else body
    CONSOLE.print(Panel(panel_body, title=title, border_style="yellow", title_align="left"))
    return Confirm.ask("Apply this change?", default=False)
