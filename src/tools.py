"""
src/tools.py
------------
Every function here is a tool the agent can call. All flat, top-level
functions -- no factories, no closures, no nesting. Each one operates on
the CURRENT DIRECTORY (os.getcwd()) as the project root, since that's
where you run `miniagent` from.

The @tool decorator (from langchain_core) turns each function into a
LangChain tool automatically, using the function's type hints and
docstring to build its schema -- that's the whole reason there's no
manual JSON schema anywhere in this file.
"""

import ast
import os
import subprocess

from langchain_core.tools import tool


class ToolError(Exception):
    """Raised when a tool can't complete safely. Message is shown to the LLM."""
    pass


def _safe_path(relative_path: str) -> str:
    """
    Resolve relative_path against the current directory and make sure the result stays INSIDE it. Stops the agent from reading/writing files outside the project, e.g. relative_path='../../etc/passwd'.
    """

    root = os.path.abspath(os.getcwd())
    full_path = os.path.abspath(os.path.join(root, relative_path))
    if not full_path.startswith(root + os.sep) and full_path != root:
        raise ToolError(f"Refused: '{relative_path}' resolves outside the project directory.")
    return full_path


@tool
def list_directory(path: str = ".") -> str:
    """List all files and folders under `path`, recursively, skipping junk directories like .git, __pycache__, node_modules. Use path='.' for the project root (the current directory)."""
    try:
        target = _safe_path(path)
        if not os.path.exists(target):
            return f"ERROR: Path does not exist: {path}"

        ignore = {".git", "__pycache__", "node_modules", ".venv", "venv"}
        lines = []
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if d not in ignore]
            rel_dir = os.path.relpath(dirpath, os.getcwd())
            depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
            indent = "  " * depth
            if rel_dir != ".":
                lines.append(f"{indent}{os.path.basename(dirpath)}/")
            for f in sorted(filenames):
                file_indent = "  " * (depth + 1) if rel_dir != "." else "  "
                lines.append(f"{file_indent}{f}")
        return "\n".join(lines) if lines else "(empty directory)"
    except ToolError as e:
        return f"ERROR: {e}"


@tool
def read_file(path: str) -> str:
    """Read a file's full content with line numbers prefixed, e.g. '  12\\tsome code'. Always read a file before editing it."""
    try:
        target = _safe_path(path)

        if not os.path.isfile(target):
            return f"ERROR: File does not exist: {path}"

        with open(target, "r", encoding="utf-8") as f:
            lines = f.readlines()
        numbered = [f"{i + 1:>4}\t{line}" for i, line in enumerate(lines)]

        return "".join(numbered) if numbered else "(empty file)"
    except ToolError as e:
        return f"ERROR: {e}"


@tool
def get_file_outline(path: str) -> str:
    """Get a compact structural summary of a Python file: function/class
    names, arguments with type hints, return types, and docstrings --
    WITHOUT full function bodies. Use this on large files before deciding
    whether you need the full read_file content."""
    try:
        target = _safe_path(path)
        if not os.path.isfile(target):
            return f"ERROR: File does not exist: {path}"
        if not path.endswith(".py"):
            return "ERROR: get_file_outline only supports .py files"

        with open(target, "r", encoding="utf-8") as f:
            source = f.read()
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return f"ERROR: Could not parse {path}: {e}"

        lines = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = []
                for a in node.args.args:
                    ann = f": {ast.unparse(a.annotation)}" if a.annotation else ""
                    args.append(f"{a.arg}{ann}")
                ret = f" -> {ast.unparse(node.returns)}" if node.returns else "None"
                doc = ast.get_docstring(node)
                lines.append(f"def {node.name}({', '.join(args)}){ret}  (line {node.lineno})")
                if doc:
                    lines.append(f"    \"\"\"{doc}\"\"\"")
            elif isinstance(node, ast.ClassDef):
                lines.append(f"class {node.name}  (line {node.lineno})")
                doc = ast.get_docstring(node)
                if doc:
                    lines.append(f"    \"\"\"{doc}\"\"\"")
        return "\n".join(lines) if lines else "(no top-level functions or classes found)"
    except ToolError as e:
        return f"ERROR: {e}"


@tool
def edit_file(path: str, old_str: str, new_str: str) -> str:
    """Replace an exact, unique block of text in an existing file with new
    text. old_str must match the file's existing content exactly, including
    whitespace/indentation, and must appear exactly once in the file. Use
    this for ALL edits to existing files -- do not use write_file for
    existing files."""
    try:
        target = _safe_path(path)
        if not os.path.isfile(target):
            return f"ERROR: File does not exist: {path}"

        with open(target, "r", encoding="utf-8") as f:
            content = f.read()

        count = content.count(old_str)
        if count == 0:
            return ("ERROR: old_str not found in file. Re-read the file to get the "
                     "exact text (whitespace/indentation must match exactly).")
        if count > 1:
            return (f"ERROR: old_str appears {count} times in the file -- it must be "
                     "unique. Include more surrounding context to disambiguate.")

        new_content = content.replace(old_str, new_str)
        with open(target, "w", encoding="utf-8") as f:
            f.write(new_content)
        return f"Edit applied to {path}"
    except ToolError as e:
        return f"ERROR: {e}"


@tool
def write_file(path: str, content: str) -> str:
    """Create a brand new file, or fully overwrite an existing one. Prefer
    edit_file for existing files -- only use this for files that don't
    exist yet."""
    try:
        target = _safe_path(path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote {len(content)} chars to {path}"
    except ToolError as e:
        return f"ERROR: {e}"


@tool
def run_bash(command: str) -> str:
    """Run a shell command inside the project directory, e.g. to run tests,
    check that a module imports cleanly, or run git diff. 30 second
    timeout. Use this to VERIFY your changes after editing."""
    try:
        result = subprocess.run(
            command, shell=True, cwd=os.getcwd(),
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    output = f"exit_code: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}\n"
    return output[:4000]


TOOLS = [list_directory, read_file, get_file_outline, edit_file, write_file, run_bash]
