"""
minicode/__init__.py
---------------------
Minimal AI coding agent. Always operates on the CURRENT DIRECTORY -- run
`minicode` from inside the project you want it to work on. Output streams
in real time as the agent works (text word-by-word, tool calls/results as
they happen, with syntax-highlighted code and colored diffs) -- similar
to Claude Code's terminal output.

Edits and file writes require your approval in the terminal before they're
applied (see confirm() in utils.py).

Swap models by editing the MODEL variable below. Format is
"provider:model-name" (this is what LangChain's init_chat_model expects).

Two ways to run it:

  Single task, one-shot:
      minicode "add a new route to delete a todo item"

  Interactive session (remembers earlier turns in the same session):
      minicode
      > add a new route to delete a todo item
      > now add a bulk-delete endpoint too
      > exit

Memory is in-memory only (InMemorySaver) -- it lives for the life of this
one process and is gone once you exit. That's why memory across turns
only works in interactive mode: each single-shot `minicode "task"` call
is a brand new process with nothing to remember.
"""

import os
import sys
import uuid
from dotenv import load_dotenv

load_dotenv()

from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
from rich.syntax import Syntax

from tools import TOOLS
from utils import CONSOLE, guess_lexer, strip_line_numbers

# --- Swap the model here. Format: "provider:model-name" ---
MODEL = "deepseek:deepseek-v4-pro"
# MODEL = "anthropic:claude-sonnet-5"
# MODEL = "openai:gpt-4.1-mini"
# MODEL = "google_genai:gemini-2.0-flash"
# MODEL = "groq:llama-3.3-70b-versatile"
# MODEL = "ollama:llama3.1"          # local, no API key needed
# ------------------------------------------------------------

SYSTEM_PROMPT = """You are a careful AI coding agent working inside an existing project
(the current working directory).

## There is no tool for reading a whole file. Do not try.

You do NOT have a read_file tool, and there is no other way to dump an
entire file's content in one call -- whole-file dumps via run_bash (cat,
less, more, type, or similar with no filtering) are also blocked and will
return an error. If a tool call fails because a tool doesn't exist, that
means the tool doesn't exist -- do not retry it, and do not fall back to
a shell command to work around it. Use the tools below instead.

## Search first, narrow second, view small chunks last

1. When the task names a piece of functionality (e.g. "login route",
   "delete a todo", "user auth"), first brainstorm 3-6 likely naming
   variants a developer might have used for that concept: synonyms
   (login/signin/authenticate), casing conventions (snake_case, camelCase,
   kebab-case), and common abbreviations (auth, del, rm). Different parts
   of a codebase -- or different developers -- often name the same thing
   differently.
2. Call `search_code` with those variants joined by '|', e.g.
   "login|signin|sign_in|log_in|authenticate". This returns small,
   relevant code chunks with a few lines of context -- not whole files --
   which is exactly what you need to locate the real implementation. If 2
   lines of context isn't enough to understand a match, increase
   search_code's `context` parameter (up to 10) and search again -- that
   is still far cheaper than reading a whole file.
3. If search_code finds nothing, don't give up on the first try: widen or
   change your keyword variants and search again, or use `find_files` to
   locate likely files by name first (e.g. "**/*route*/*.py"), then
   search_code within that narrower path.
4. Use `get_file_outline` for a structural overview of a specific file
   (functions/classes/docstrings, no bodies, includes line numbers) once
   you've identified it.
5. Use `read_lines(path, start_line, end_line)` only once you already know
   roughly where something is (from get_file_outline's line numbers, or a
   search_code match) and need the exact text, including whitespace, to
   construct an `edit_file` call. This is capped at 200 lines per call --
   if you're tempted to request a huge range, that's a signal to search
   more precisely instead, not to widen the range.
6. Use `list_directory` sparingly, mainly for a first orientation in an
   unfamiliar project, not as a substitute for search_code.

## Editing rules

- Prefer `edit_file` (targeted find-and-replace) over `write_file` for
  existing files. Only use `write_file` for brand new files.
- Match the existing code style and conventions you observe in the project
  (naming, import style, error handling patterns).
- After making a change, verify it: at minimum run a Python import check
  or the project's test suite via `run_bash`.
- Explain your plan briefly before making edits, then execute it with tool calls.
- edit_file and write_file require human approval and may be rejected. If one
  is rejected, do not repeat the exact same call -- explain what you were
  trying to do and ask for guidance, or propose a different approach.
- When you are done, give a short summary of what changed, which keywords/
  searches led you there, and how you verified it.
"""


def render_message_chunk(token) -> None:
    """Print the assistant's text as it's generated, token by token."""
    if getattr(token, "text", None):
        print(token.text, end="", flush=True)


def render_completed_step(source: str, message, pending_call: dict) -> None:
    """Print a tool call the moment it's decided, or a tool's result the
    moment it finishes -- with syntax highlighting for code-returning
    tools. `pending_call` carries the most recent tool name/args from the
    "model" step across to the following "tools" step, so a read_lines
    result can be highlighted using the right lexer for its file path."""
    if source == "model" and getattr(message, "tool_calls", None):
        for tc in message.tool_calls:
            pending_call["name"] = tc["name"]
            pending_call["args"] = tc["args"] or {}
            CONSOLE.print(f"\n→ {tc['name']}({tc['args']})", style="bold cyan", markup=False)
    elif source == "tools":
        content = str(message.content)
        tool_name = pending_call.get("name")
        path = (pending_call.get("args") or {}).get("path", "")

        if tool_name == "read_lines" and path:
            code = strip_line_numbers(content)[:3000]
            CONSOLE.print(Syntax(code, guess_lexer(path), theme="monokai", line_numbers=True, word_wrap=True))
        else:
            # search_code/get_file_outline/find_files/list_directory/run_bash
            # results are mixed text (grep output, status messages, etc.)
            # rather than pure source -- keep these as dimmed plain text.
            preview = content if len(content) < 1200 else content[:1200] + "\n... (truncated)"
            CONSOLE.print(preview, style="dim", markup=False)
        pending_call["name"] = None
        pending_call["args"] = None


def run_task(agent, task: str, thread_id: str) -> None:
    """Run one task on the given agent/thread and stream the output live.
    Reused by both single-shot mode and the interactive REPL, so every
    turn -- whichever mode is running -- streams and prints identically."""
    config = {"configurable": {"thread_id": thread_id}}
    pending_call = {"name": None, "args": None}

    # stream_mode=["messages", "updates"] gives two interleaved feeds:
    #   "messages" -> live (token, metadata) chunks as the model generates text,
    #                 so assistant text prints word-by-word, Claude-Code style
    #   "updates"  -> a completed message the instant a graph step finishes,
    #                 so tool calls and tool results appear as soon as they happen
    # (tool calls/results aren't generated token-by-token, so they print whole)
    for mode, chunk in agent.stream(
        {"messages": [{"role": "user", "content": task}]},
        config=config,
        stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            token, metadata = chunk
            if metadata.get("langgraph_node") == "model":
                render_message_chunk(token)
        elif mode == "updates":
            for source, update in chunk.items():
                if source in ("model", "tools"):
                    render_completed_step(source, update["messages"][-1], pending_call)

    print("\n" + "=" * 60)


def main():
    project_root = os.getcwd()
    print(f"Project directory: {project_root}")
    print(f"Model: {MODEL}")
    print("=" * 60)

    model = init_chat_model(MODEL, temperature=0)
    checkpointer = InMemorySaver()
    agent = create_agent(model=model, tools=TOOLS, system_prompt=SYSTEM_PROMPT, checkpointer=checkpointer)

    # One thread_id per process run. Every turn in this run (whether one
    # single-shot task or many turns in the REPL) shares this thread_id,
    # so the checkpointer lets the agent remember earlier turns within
    # this session. A new `minicode` process gets a fresh thread_id and
    # an empty memory -- see the module docstring for why.
    thread_id = str(uuid.uuid4())

    if len(sys.argv) >= 2:
        # Single-shot mode: one task, then exit.
        task = " ".join(sys.argv[1:])
        print(f"Task: {task}\n{'=' * 60}\n")
        run_task(agent, task, thread_id)
        return

    # Interactive mode: no task given on the command line, so start a REPL.
    # Every prompt here shares the same thread_id above, so the agent has
    # full memory of earlier turns in this session.
    print("Interactive session. Type a task and press Enter.")
    print("Type 'exit' or 'quit' (or leave blank) to stop.\n")
    while True:
        try:
            task = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break
        if not task or task.lower() in ("exit", "quit"):
            print("Exiting.")
            break
        print()
        run_task(agent, task, thread_id)
        print()


if __name__ == "__main__":
    main()
