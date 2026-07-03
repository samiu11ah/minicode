"""
tools.py
--------
Every function here is a tool the agent can call. All flat, top-level
functions -- no factories, no closures, no nesting. Each one operates on
the CURRENT DIRECTORY (os.getcwd()) as the project root, since that's
where you run `minicode` from.

Path safety, diff/code preview rendering, and the human-approval prompt
live in utils.py -- this file focuses purely on the tool definitions.
"""

import ast
import glob as glob_module
import os
import re
import subprocess

from langchain_core.tools import tool

from utils import ToolError, code_preview, confirm, diff_preview, safe_path

# Commands that dump an entire file's content with no filtering/bounding.
# run_bash blocks these so there's no shell-based escape hatch around
# search_code/read_lines being the only sanctioned ways to see file
# content. Deliberately conservative (only the clearest cases) since bash
# is expressive enough that this can't be made airtight -- the system
# prompt in minicode/__init__.py carries the rest of the enforcement.
_WHOLE_FILE_DUMP_PATTERNS = [
    r"(^|[;&|]\s*)cat\s+[^|>;&]*$",           # bare `cat file(s)`, not piped/filtered/redirected
    r"(^|[;&|]\s*)(less|more)\s+",             # pagers always show the whole file
    r"(^|[;&|]\s*)type\s+\S+\s*$",             # Windows cmd equivalent of cat
    r"(^|[;&|]\s*)sed\s+-n\s+['\"]?1,\$p",     # `sed -n '1,$p'` == print whole file
    r"(^|[;&|]\s*)awk\s+['\"]?\{\s*print\s*\}", # `awk '{print}'` == print whole file, unfiltered
]


def _looks_like_whole_file_dump(command: str) -> bool:
    return any(re.search(pattern, command.strip()) for pattern in _WHOLE_FILE_DUMP_PATTERNS)


@tool
def search_code(keywords: str, path: str = ".", context: int = 2) -> str:
    """Search the codebase for one or more keywords and return matching
    lines WITH a few lines of surrounding context (a small code chunk),
    not a whole file. This is the PRIMARY way to explore a codebase.

    Case-insensitive. To search several likely naming variants at once,
    separate them with '|' (this is regex alternation), e.g.
    'login|signin|sign_in|log_in|authenticate' -- developers name the same
    concept differently across a codebase, and checking several likely
    variants in one call finds the real name fast instead of guessing.

    context: lines of surrounding context above/below each match (default
    2, max 10). If 2 isn't enough to understand a match, increase this
    (e.g. 6-10) and search again -- that is still far cheaper than reading
    a whole file, and is the correct next step, not a fallback to shell
    commands like cat.

    Skips .git, __pycache__, node_modules, venv automatically.
    Returns 'file:line:content' for each match."""
    try:
        target = safe_path(path)
        context = max(0, min(int(context), 10))
        cmd = [
            "grep", "-rniE",
            "--exclude-dir=.git", "--exclude-dir=__pycache__",
            "--exclude-dir=node_modules", "--exclude-dir=.venv", "--exclude-dir=venv",
            "-C", str(context),
            "--", keywords, target,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        output = result.stdout.strip()
        if not output:
            return (f"No matches for '{keywords}' under {path}. Try different keyword "
                     "variants: synonyms, snake_case/camelCase, abbreviations, or a "
                     "broader/narrower path.")
        cwd_prefix = os.path.abspath(os.getcwd()) + os.sep
        output = output.replace(cwd_prefix, "")
        return output[:4000]
    except ToolError as e:
        return f"ERROR: {e}"
    except FileNotFoundError:
        return "ERROR: grep is not available on this system."
    except subprocess.TimeoutExpired:
        return "ERROR: search timed out after 15 seconds. Try a narrower path or fewer keywords."


@tool
def find_files(pattern: str) -> str:
    """Find files by NAME pattern using glob syntax. Standard glob rules:
    '*' matches within one path segment, '**' matches across any number of
    directories. To match a file NAME containing a word, use e.g.
    '**/*auth*.py'. To match files inside a directory whose NAME contains
    a word, include that segment explicitly, e.g. '**/*route*/*.py' or
    '**/routes/*.py'. Use this to locate likely-relevant files by name
    (not by content -- use search_code for that). Skips .git, __pycache__,
    node_modules, venv."""
    if pattern.startswith("/") or ".." in pattern.split("/"):
        return "ERROR: pattern must be a relative path within the project directory."
    try:
        matches = glob_module.glob(pattern, recursive=True)
        ignore = {".git", "__pycache__", "node_modules", ".venv", "venv"}
        matches = [m for m in matches if not any(part in ignore for part in m.split(os.sep))]
        matches = sorted(m for m in matches if os.path.isfile(m))
        return "\n".join(matches) if matches else f"No files matched pattern: {pattern}"
    except Exception as e:
        return f"ERROR: {e}"


@tool
def list_directory(path: str = ".") -> str:
    """List all files and folders under `path`, recursively, skipping junk
    directories like .git, __pycache__, node_modules. Use path='.' for the
    project root (the current directory)."""
    try:
        target = safe_path(path)
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
def read_lines(path: str, start_line: int, end_line: int) -> str:
    """Read a BOUNDED range of lines from a file (max 200 lines per call),
    with line numbers prefixed. There is NO tool for reading a whole file
    -- use this only once you already know roughly where something is
    (e.g. get_file_outline gave you a line number, or a search_code match
    is close to a line you need more context around) and you need the
    exact text, including whitespace, to construct an edit_file call.
    If you don't yet know where to look, use search_code first, not this."""
    try:
        target = safe_path(path)
        if not os.path.isfile(target):
            return f"ERROR: File does not exist: {path}"
        if start_line < 1 or end_line < start_line:
            return "ERROR: start_line must be >= 1 and end_line >= start_line."
        if end_line - start_line + 1 > 200:
            return "ERROR: range too large (max 200 lines per call). Narrow the range."

        with open(target, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if start_line > len(lines):
            return f"ERROR: file only has {len(lines)} lines."

        selected = lines[start_line - 1:end_line]
        numbered = [f"{start_line + i:>4}\t{line}" for i, line in enumerate(selected)]
        return "".join(numbered) if numbered else "(no lines in that range)"
    except ToolError as e:
        return f"ERROR: {e}"


@tool
def get_file_outline(path: str) -> str:
    """Get a compact structural summary of a Python file: function/class
    names, arguments with type hints, return types, and docstrings --
    WITHOUT full function bodies. Use this on large files to find line
    numbers to target with read_lines, instead of reading the whole file."""
    try:
        target = safe_path(path)

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
                ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
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
    existing files. This tool requires human approval before applying."""
    try:
        target = safe_path(path)
        if not os.path.isfile(target):
            return f"ERROR: File does not exist: {path}"

        with open(target, "r", encoding="utf-8") as f:
            content = f.read()

        count = content.count(old_str)
        if count == 0:
            return ("ERROR: old_str not found in file. Use search_code or read_lines to "
                     "get the exact current text (whitespace/indentation must match exactly).")
        if count > 1:
            return (f"ERROR: old_str appears {count} times in the file -- it must be "
                     "unique. Include more surrounding context to disambiguate.")

        diff = diff_preview(path, old_str, new_str)
        if not confirm(f"Edit {path}:", diff):
            return ("EDIT REJECTED by the human reviewer. Do not repeat this exact "
                     "edit. Explain what you were trying to do and ask for guidance, "
                     "or propose a different approach if one is reasonable.")

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
    exist yet. This tool requires human approval before applying."""
    try:
        target = safe_path(path)
        exists = os.path.isfile(target)
        action = "Overwrite existing file" if exists else "Create new file"
        preview = code_preview(path, content)
        if not confirm(f"{action} {path}:", preview):
            return ("WRITE REJECTED by the human reviewer. Do not repeat this exact "
                     "write. Explain what you were trying to do and ask for guidance, "
                     "or propose a different approach if one is reasonable.")

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
    timeout. Use this to VERIFY your changes after editing -- NOT to read
    file content. Whole-file dumps (cat/less/more/type with no filtering,
    or similar) are blocked; use search_code or read_lines instead."""
    if _looks_like_whole_file_dump(command):
        return (
            "ERROR: This looks like a whole-file dump (e.g. cat/less/more with no "
            "filtering) -- reading whole files is not allowed, including via shell "
            "commands. Use search_code with relevant keywords to see the specific "
            "chunk you need, get_file_outline for structure, or read_lines with a "
            "specific bounded line range if you already know where to look."
        )
    try:
        result = subprocess.run(
            command, shell=True, cwd=os.getcwd(),
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    output = f"exit_code: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}\n"
    return output[:4000]


TOOLS = [search_code, find_files, list_directory, read_lines, get_file_outline, edit_file, write_file, run_bash]
