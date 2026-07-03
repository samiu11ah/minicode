# mini-coding-agent

A minimal, provider-agnostic AI coding agent, packaged as an installable
CLI tool with `uv`. Once installed, run `miniagent "<task>"` from inside
any project directory.

## Project layout

```
mini-coding-agent/
├── pyproject.toml       # package manifest, console script entry point
├── README.md
├── src/                  # the installable package
│   ├── __init__.py
│   ├── agent.py           # entry point -- edit MODEL here
│   └── tools.py            # all agent tools
└── fastapi-todo/          # demo project to test the agent against
    ├── main.py
    └── src/
        ├── core/config.py
        ├── database/models.py
        └── routes/todo_crud.py
```

`cli/` and `fastapi-todo/` are siblings on purpose: `cli/` is the tool,
`fastapi-todo/` is just one example of a project you'd point it at. The
agent never assumes anything about `fastapi-todo/` specifically — it
works on whatever directory you run it from.

## Install with uv

From the `mini-coding-agent/` root:

```bash
# Create and activate a virtual environment
uv venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# Editable install, so changes to cli/agent.py and cli/tools.py take
# effect immediately without reinstalling. Pick the extra(s) for the
# provider(s) you'll use:
uv pip install -e ".[anthropic]"
uv pip install -e ".[deepseek]"
uv pip install -e ".[anthropic,deepseek,openai]"   # several at once
uv pip install -e ".[all]"                          # every provider
```

This registers the `miniagent` command (from `[project.scripts]` in
`pyproject.toml`) inside your virtual environment.

Set the API key for whichever provider(s) you installed:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export DEEPSEEK_API_KEY="sk-..."
# etc.
```

## Run it

```bash
cd fastapi-todo
miniagent "add a new route to delete a todo item"
```

The agent always operates on the current directory — no `--project` flag.
Run it from inside whatever project you want it to work on.

## Swap models

Open `cli/agent.py` and change one line:

```python
MODEL = "anthropic:claude-sonnet-5"
# MODEL = "deepseek:deepseek-chat"
# MODEL = "openai:gpt-4.1-mini"
# MODEL = "google_genai:gemini-2.0-flash"
# MODEL = "groq:llama-3.3-70b-versatile"
# MODEL = "ollama:llama3.1"          # local, no API key
```

Since the install is editable (`-e`), the change takes effect the next
time you run `miniagent` — no reinstall needed.

Format is `"provider:model-name"` (colon) — this is what LangChain's
`init_chat_model` expects. Whatever you put after the colon is passed
straight through, so new model names work immediately with zero code
changes.

## Real-time streaming output

Output prints as it happens, not all at once after the run finishes:

- **Assistant text** streams word-by-word, as the model generates it
- **Tool calls** print the moment the model decides to make one (e.g.
  `[tool_call] edit_file(...)`)
- **Tool results** print the moment the tool finishes running (e.g.
  `[tool_result] Edit applied to ...`)

This is done with `agent.stream(inputs, stream_mode=["messages", "updates"])`
instead of `agent.invoke(...)`:

- `stream_mode="messages"` yields `(token, metadata)` pairs as the model
  generates text -- this is what makes assistant text print token-by-token
- `stream_mode="updates"` yields a completed message the instant a graph
  step finishes -- tool calls and tool results aren't generated
  incrementally the way text is, so they print whole, as soon as they're
  ready, rather than character-by-character

```python
for mode, chunk in agent.stream(
    {"messages": [{"role": "user", "content": task}]},
    stream_mode=["messages", "updates"],
):
    if mode == "messages":
        token, metadata = chunk
        if metadata.get("langgraph_node") == "model":
            render_message_chunk(token)      # print text tokens live
    elif mode == "updates":
        for source, update in chunk.items():
            if source in ("model", "tools"):
                render_completed_step(source, update["messages"][-1])  # print tool call/result
```

## Search-first exploration (not whole-file reads)

The agent now prioritizes grep-style search over reading whole files.
Two new tools drive this:

- **`search_code(keywords, path=".")`** — greps the codebase and returns
  matching lines with 2 lines of context each (a small chunk), not a
  whole file. Supports multiple keyword variants at once via `|`, e.g.
  `"login|signin|sign_in|log_in"` — since developers name the same
  concept differently across a codebase, checking several likely variants
  in one call finds the real implementation fast instead of guessing.
- **`find_files(pattern)`** — locates files by glob pattern, e.g.
  `"**/*route*/*.py"`, when you need to narrow down *where* to look before
  searching *what's* there.

The system prompt now spells out the workflow explicitly:

1. Brainstorm 3-6 likely naming variants for the concept in the task
   (synonyms, casing conventions, abbreviations)
2. `search_code` with those variants joined by `|`
3. If nothing matches, widen the variants and search again, or narrow
   down with `find_files` first
4. `get_file_outline` once a file's identified, for a structural view
5. `read_file` only once you already know it's the right file and need
   exact text for an `edit_file` call — this is now the *last* resort,
   not the first move

```bash
cd fastapi-todo
miniagent "add a route to delete a todo item"
```

Watch the trace: instead of immediately reading `todo_crud.py` in full,
the agent should call `search_code` with something like
`"todo_id|delete|remove"` first, see the relevant chunk, and only then
either go straight to `edit_file` or do a quick `read_file` to get exact
surrounding text.

**Why `search_code` shells out to `grep` via a fixed argument list (not
`run_bash` with a string)**: building the command as a Python list
(`["grep", "-rniE", ..., "--", keywords, target]`) avoids shell string
interpolation entirely, so a keyword pattern containing quotes or shell
metacharacters can't break out of the intended command. `run_bash` still
exists separately for genuinely arbitrary commands (tests, `git diff`,
etc.) — it just isn't the tool used for routine code exploration anymore.

## Colored diffs & syntax-highlighted code

Terminal output now looks like an IDE instead of plain text, using
[`rich`](https://github.com/Textualize/rich) (which bundles Pygments for
language-aware highlighting):

- **Edit approval prompts** show a colored unified diff (`+` lines green,
  `-` lines red, `@@` hunk headers highlighted) instead of plain text —
  built with `Syntax(diff_text, "diff", theme="monokai")`, using
  Pygments' built-in diff lexer.
- **`write_file` approval prompts** show the new file's content with full
  language-aware syntax highlighting (keywords, strings, comments colored
  appropriately), using a lexer guessed from the file's extension.
- **`read_file` results** are re-rendered in the terminal with syntax
  highlighting and clean line numbers (the raw tool output sent to the
  LLM keeps its own `N\t` line-number prefixes for the model's benefit —
  those are stripped before re-numbering nicely for the human).
- **Other tool results** (`search_code`, `get_file_outline`, `find_files`,
  `list_directory`, `run_bash`) print as dimmed plain text, since grep
  output and status messages aren't source code and don't benefit from a
  language lexer.

**Important separation, worth understanding:** none of this coloring ever
reaches the model. Every tool still *returns* a plain string (what's in
`cli/tools.py`) — that's what gets appended to the conversation and sent
to the LLM. The `rich` rendering only happens in the human-facing print
calls (`_confirm()` in `cli/tools.py`, and `render_completed_step()` in
`cli/agent.py`), which are a separate step from what the model receives.
This also matters for safety: tool/file content is arbitrary text that
could coincidentally look like Rich markup (e.g. a string like `[bold]`
inside someone's code) — every print of untrusted content passes
`markup=False` explicitly, so it's always displayed literally rather than
being interpreted as a formatting instruction. `Syntax` objects are
inherently safe here too, since they render code as literal text, never
as markup.

**Theme:** all highlighting uses Pygments' `"monokai"` theme, chosen since
it reads well on both dark and most light terminal backgrounds. To change
it, edit the `theme="monokai"` argument anywhere `Syntax(...)` is
constructed in `cli/tools.py` and `cli/agent.py` — any
[Pygments style name](https://pygments.org/styles/) works (e.g.
`"dracula"`, `"github-dark"`, `"nord"`).

## Human approval before edits

`edit_file` and `write_file` now pause and ask you to approve before
touching disk. You'll see a diff-style preview and a prompt:

```
------------------------------------------------------------
[approval needed]
Edit src/routes/todo_crud.py:
--- src/routes/todo_crud.py (before)
+++ src/routes/todo_crud.py (after)
@@ -1,4 +1,12 @@
 @router.get("/todos/{todo_id}")
 def get_todo(todo_id: int):
     """Fetch a single todo item by id."""
-    return find_todo_or_404(todo_id)
+    return find_todo_or_404(todo_id)
+
+
+@router.delete("/todos/{todo_id}")
+def delete_todo(todo_id: int):
+    ...
------------------------------------------------------------
Apply this change? [y/N]
```

Typing anything other than `y`/`yes` rejects the change — the file stays
untouched, and the agent gets a message telling it not to repeat the
exact same edit. `list_directory`, `read_file`, `get_file_outline`, and
`run_bash` stay ungated since they don't mutate anything (well, `run_bash`
technically can — see the note below).

This lives in `cli/tools.py`: `_confirm()` prints the prompt and blocks on
`input()`, and `_diff_preview()` builds the unified diff using Python's
built-in `difflib`. Both are called directly inside `edit_file`/`write_file`
before the actual file write happens.

**Note:** `run_bash` isn't gated by default. It's mostly used for
read-only verification (running tests, checking an import), but it *can*
run destructive commands. If you want it gated too, wrap its body the
same way `edit_file` does — call `_confirm()` before `subprocess.run()`.

## Thread memory (in-memory)

The agent now remembers earlier turns *within one running session*, using
LangGraph's `InMemorySaver` checkpointer keyed by a `thread_id`.

```bash
miniagent
> add a new route to delete a todo item
[... agent works, asks for approval, applies the edit ...]

> now add a bulk-delete endpoint too
[... agent remembers the delete route it just added, builds on it ...]

> exit
```

**Important limitation, by design (you asked for "in memory, for now"):**
memory only survives for the life of one `miniagent` process. Single-shot
mode (`miniagent "task"`) still works exactly as before, but each call is
a fresh process with a fresh, empty `InMemorySaver` — there's no memory
*between* separate command invocations, only *within* one interactive
session. To get memory that survives across separate `miniagent` calls
(or restarts), swap `InMemorySaver` for a persistent checkpointer, e.g.:

```python
# pip install langgraph-checkpoint-sqlite
from langgraph.checkpoint.sqlite import SqliteSaver

with SqliteSaver.from_conn_string("miniagent_memory.db") as checkpointer:
    agent = create_agent(model=model, tools=TOOLS, system_prompt=SYSTEM_PROMPT, checkpointer=checkpointer)
    ...
```

No other code changes needed — `create_agent`, `run_task`, and the
`thread_id` plumbing all stay the same; only the checkpointer object
changes. This is a natural next step to build on camera.

## How the package wiring works

- **`pyproject.toml`**'s `[project.scripts]` maps the command `miniagent`
  to the function `src.agent:main` — i.e. "run `main()` inside `cli/agent.py`".
  This is what turns a plain Python function into a terminal command after
  install.
- **`[tool.hatch.build.targets.wheel] packages = ["src"]`** tells the
  build backend (hatchling) that the `src/` folder is the package to
  include — necessary here since the distribution name
  (`mini-coding-agent`) doesn't match the importable package name (`cli`).
- **`cli/agent.py`** imports its tools with `from src.tools import TOOLS`
  — a normal absolute import that works because, once installed, `cli` is
  a real top-level package on the Python path.
- **Optional dependencies** (`[project.optional-dependencies]`) keep
  provider SDKs opt-in. Installing the base package alone only pulls in
  `langchain` + `langchain-core` — nothing provider-specific until you
  request an extra.

## Publishing this later (optional, for when you're ready)

```bash
uv build          # produces a wheel + sdist in dist/
uv publish         # uploads to PyPI (needs credentials configured)
```

One naming note if you do this: the importable package is literally
named `cli`, which is a very generic name and could collide with another
installed package also using top-level `import cli`. Fine for local/
personal use; if you publish for others to install alongside other tools,
consider renaming the folder (and the `packages = [...]` line, and every
`from src...` import) to something more specific, e.g. `miniagent_core`.

## Note on this environment

I couldn't run `uv pip install` here (no network access in this sandbox),
so the live model call couldn't be exercised end-to-end, and I couldn't
install the real `rich` package either. I did verify everything that
doesn't require the real packages, using lightweight local stubs standing
in for `langchain`/`langgraph`/`langchain_core`/`rich`:

- `pyproject.toml` parses correctly; all `.py` files compile cleanly
- `cli/agent.py`'s package-relative imports resolve correctly
- `guess_lexer()` was tested directly: correct lexer names for `.py`,
  `.toml`, `.md`, and an unknown extension (falls back to `"text"`)
- `_diff_preview()` was tested directly against the real add-delete-route
  edit: confirmed it builds a `Syntax(diff_text, "diff", ...)` object with
  the correct diff content (verified via a stub `Syntax` class that
  echoes back exactly what it was constructed with)
- The full approval flow was re-run end-to-end through `edit_file`:
  approving applies the edit correctly with the diff preview rendered;
  the file was reset and confirmed clean afterward
- `render_completed_step()` was tested via a simulated `search_code` →
  `read_file` sequence: confirmed the `pending_call` tracking correctly
  carries the file path from the `read_file` tool call over to its
  result, so the syntax highlighting uses the right lexer (`python` in
  the test) and the `N\t` line-number prefixes are correctly stripped
  before re-highlighting; confirmed `search_code` results are NOT
  syntax-highlighted (rendered as plain dimmed text), as intended

I could not verify actual terminal color rendering, since that requires
the real `rich` package (my stub just proves the correct objects are
built with the correct content/lexer — it doesn't render ANSI color
codes). Do a real `uv pip install -e .` and look at actual colored output
in your own terminal before recording.
