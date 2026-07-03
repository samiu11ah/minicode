"""
utils.py
--------
Shared helpers used by both tools.py (tool implementations) and
minicode/__init__.py (the agent loop / terminal rendering).

Everything path-safety-related and everything rich/Pygments-rendering-
related lives here, so tools.py stays focused on the tool functions
themselves and minicode/__init__.py stays focused on the agent loop.
"""

import difflib
import os

from rich.console import Console
from rich.syntax import Syntax

CONSOLE = Console()

# Extension -> Pygments lexer name, used to syntax-highlight file content
# in the terminal (for the human, never sent to the LLM). Falls back to
# plain "text" for anything not listed.
EXT_TO_LEXER = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".json": "json",
    ".md": "markdown", ".html": "html", ".css": "css", ".scss": "scss",
    ".sh": "bash", ".bash": "bash", ".yaml": "yaml", ".yml": "yaml",
    ".sql": "sql", ".toml": "toml", ".go": "go", ".rs": "rust",
    ".java": "java", ".rb": "ruby", ".php": "php", ".c": "c",
    ".cpp": "cpp", ".cs": "csharp", ".xml": "xml",
}


class ToolError(Exception):
    """Raised when a tool can't complete safely. Message is shown to the LLM."""
    pass


def guess_lexer(path: str) -> str:
    """Guess a Pygments lexer name from a file's extension."""
    ext = os.path.splitext(path)[1].lower()
    return EXT_TO_LEXER.get(ext, "text")


def safe_path(relative_path: str) -> str:
    """
    Resolve relative_path against the current directory and make sure the
    result stays INSIDE it. Stops the agent from reading/writing files
    outside the project, e.g. relative_path='../../etc/passwd'.
    """
    root = os.path.abspath(os.getcwd())
    full_path = os.path.abspath(os.path.join(root, relative_path))
    if not full_path.startswith(root + os.sep) and full_path != root:
        raise ToolError(f"Refused: '{relative_path}' resolves outside the project directory.")
    return full_path


def strip_line_numbers(content: str) -> str:
    """read_lines prefixes each line with 'NNNN\\t' for the LLM's benefit.
    Strip that before syntax-highlighting for the human, since Syntax adds
    its own (nicer) line numbers."""
    stripped_lines = []
    for line in content.splitlines():
        prefix, sep, rest = line.partition("\t")
        if sep and prefix.strip().isdigit():
            stripped_lines.append(rest)
        else:
            stripped_lines.append(line)
    return "\n".join(stripped_lines)


def diff_preview(path: str, old_str: str, new_str: str):
    """Build a colored, syntax-highlighted unified-diff view of an edit,
    for the human to review. Returns a Rich Syntax object (or a plain
    string if there's nothing to show) -- Syntax renders its content
    literally, so this is safe even if the diff text itself contains
    characters that would otherwise look like markup."""
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
    """Build a syntax-highlighted preview of a file's content (for
    write_file's approval prompt), using a lexer guessed from the path."""
    preview_text = content if len(content) < max_chars else content[:max_chars] + "\n... (truncated)"
    return Syntax(preview_text, guess_lexer(path), theme="monokai", line_numbers=True, word_wrap=True)


def confirm(header: str, body) -> bool:
    """Ask the human in the terminal to approve an action. Blocks until
    answered. `body` can be a plain string or a Rich renderable (e.g. from
    diff_preview/code_preview) for colored/highlighted output."""
    CONSOLE.print()
    CONSOLE.print("-" * 60, style="yellow", markup=False)
    CONSOLE.print("[approval needed]", style="bold yellow", markup=False)
    CONSOLE.print(header, style="bold", markup=False)
    if isinstance(body, str):
        CONSOLE.print(body, markup=False)
    else:
        CONSOLE.print(body)  # Syntax renderable -- never interprets markup
    CONSOLE.print("-" * 60, style="yellow", markup=False)
    answer = input("Apply this change? [y/N] ").strip().lower()
    return answer in ("y", "yes")
