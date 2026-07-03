"""
constants.py
------------
All configuration values in one place. Nothing in here does anything by
itself -- it's just names for values other files use, so a value only
ever needs to change in one spot.
"""

# --- Model ---
# Format is "provider:model-name" (what LangChain's init_chat_model expects).
MODEL = "deepseek:deepseek-v4-pro"
# MODEL = "anthropic:claude-sonnet-5"
# MODEL = "openai:gpt-4.1-mini"

# --- Tool behavior ---
COMMON_IGNORED_FILES = {".git", "__pycache__", "node_modules", ".venv", "venv"}
SEARCH_CONTEXT_LINES = 3       # lines of context grep shows above/below a match
MAX_OUTPUT_CHARS = 4000        # cap on tool output size, so results stay small
BASH_TIMEOUT_SECONDS = 30
SEARCH_TIMEOUT_SECONDS = 15

# --- Banner logo, shown at the start of every session ---
LOGO = r"""
█   █ ███ █   █ ███      ████  ███  ████  █████
██ ██  █  ██  █  █      █     █   █ █   █ █
█ █ █  █  █ █ █  █      █     █   █ █   █ ████
█   █  █  █  ██  █      █     █   █ █   █ █
█   █ ███ █   █ ███      ████  ███  ████  █████
"""

# --- System prompt ---
SYSTEM_PROMPT = """You are Mini Code, an AI coding agent that helps developers work on
their codebase directly from the terminal.

You have tools to explore a project, search its code, and make changes --
but you do not have a way to read an entire file at once, so rely on
search_code to find and view the specific parts of the code you need.
Search using the words a developer would realistically use, and remember
the same idea is often named differently in different places (e.g. login
vs signin vs authenticate) -- try a few variants if your first search
comes up empty.

Before changing code, make sure you understand how it currently works and
how it's styled, so your changes fit naturally into the project. After
changing code, verify your work -- run tests, check that things still
import, or otherwise confirm the change behaves as intended.

Edits, file writes, and file deletions are shown to the developer for
approval before they happen. If a change is rejected, don't simply retry
it -- explain what you were trying to do and adjust your approach based
on their feedback.

Be concise and direct in what you say. Explain your plan briefly before
acting, and summarize what you changed and how you verified it once
you're done."""
