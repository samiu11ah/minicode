"""
tools.py
--------
Six tools, six functions, nothing scattered. Each one operates on the
CURRENT DIRECTORY, since that's where you run `minicode` from.

There is no "read whole file" tool on purpose -- search_code is how the
agent sees code, in small relevant chunks instead of entire files.
"""

import os
import subprocess

from langchain_core.tools import tool

from .constants import BASH_TIMEOUT_SECONDS, COMMON_IGNORED_FILES, MAX_OUTPUT_CHARS, SEARCH_CONTEXT_LINES, SEARCH_TIMEOUT_SECONDS
from .rich_text_service import code_preview, confirm, diff_preview
from .utils import ToolError, safe_path


@tool
def list_directory(path: str = ".") -> str:
    """List files and folders under `path`, recursively. Use path='.' for
    the project root. Good for a first look around a project."""
    try:
        target = safe_path(path)
        lines = []
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if d not in COMMON_IGNORED_FILES]
            rel_dir = os.path.relpath(dirpath, os.getcwd())
            depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
            if rel_dir != ".":
                lines.append("  " * depth + os.path.basename(dirpath) + "/")
            for name in sorted(filenames):
                lines.append("  " * (depth + 1) + name)
        return "\n".join(lines) if lines else "(empty directory)"
    except ToolError as e:
        return f"ERROR: {e}"


@tool
def search_code(keywords: str, path: str = ".") -> str:
    """Search the codebase for keywords and return matching lines with a
    few lines of surrounding context -- a small chunk, not a whole file.
    This is how you see code content; there is no whole-file read tool.

    Separate multiple likely naming variants with '|', e.g.
    'login|signin|sign_in' -- the same idea is often named differently in
    different places."""
    try:
        target = safe_path(path)
        exclude = [f"--exclude-dir={d}" for d in COMMON_IGNORED_FILES]
        cmd = ["grep", "-rniE", *exclude, "-C", str(SEARCH_CONTEXT_LINES), "--", keywords, target]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=SEARCH_TIMEOUT_SECONDS)
        output = result.stdout.strip()
        if not output:
            return f"No matches for '{keywords}'. Try different keyword variants."
        cwd_prefix = os.path.abspath(os.getcwd()) + os.sep
        return output.replace(cwd_prefix, "")[:MAX_OUTPUT_CHARS]
    except ToolError as e:
        return f"ERROR: {e}"
    except subprocess.TimeoutExpired:
        return "ERROR: search timed out."


@tool
def run_bash(command: str) -> str:
    """Run a shell command in the project directory, e.g. to run tests or
    check that a module imports cleanly. Use this to VERIFY changes, not
    to read file content -- use search_code for that instead."""
    try:
        result = subprocess.run(
            command, shell=True, cwd=os.getcwd(),
            capture_output=True, text=True, timeout=BASH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out."
    output = f"exit_code: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return output[:MAX_OUTPUT_CHARS]


@tool
def write_file(path: str, content: str) -> str:
    """Create a new file, or fully overwrite an existing one. Requires
    human approval before applying."""
    try:
        target = safe_path(path)
        exists = os.path.isfile(target)
        title = f"Overwrite {path}" if exists else f"Create {path}"
        if not confirm(title, code_preview(path, content)):
            return "REJECTED by the human reviewer. Do not repeat this exact write."

        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote {len(content)} chars to {path}"
    except ToolError as e:
        return f"ERROR: {e}"


@tool
def edit_file(path: str, old_str: str, new_str: str) -> str:
    """Replace an exact, unique block of text in a file with new text.
    old_str must match the file's current content exactly, including
    whitespace, and appear exactly once. Requires human approval."""
    try:
        target = safe_path(path)
        if not os.path.isfile(target):
            return f"ERROR: File does not exist: {path}"

        with open(target, "r", encoding="utf-8") as f:
            content = f.read()

        count = content.count(old_str)
        if count == 0:
            return "ERROR: old_str not found. Use search_code to get the exact current text."
        if count > 1:
            return f"ERROR: old_str appears {count} times -- include more context to make it unique."

        if not confirm(f"Edit {path}", diff_preview(path, old_str, new_str)):
            return "REJECTED by the human reviewer. Do not repeat this exact edit."

        with open(target, "w", encoding="utf-8") as f:
            f.write(content.replace(old_str, new_str))
        return f"Edit applied to {path}"
    except ToolError as e:
        return f"ERROR: {e}"


@tool
def delete_file(path: str) -> str:
    """Delete a file. Requires human approval -- this cannot be undone."""
    try:
        target = safe_path(path)
        if not os.path.isfile(target):
            return f"ERROR: File does not exist: {path}"

        if not confirm(f"Delete {path}", "This cannot be undone."):
            return "REJECTED by the human reviewer."

        os.remove(target)
        return f"Deleted {path}"
    except ToolError as e:
        return f"ERROR: {e}"


TOOLS = [list_directory, search_code, run_bash, write_file, edit_file, delete_file]
