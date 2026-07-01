from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from tools import TOOLS

memory = InMemorySaver()

SYSTEM_PROMPT = """You are a careful AI coding agent working inside an existing project
(the current working directory).

Rules you must follow:
- ALWAYS read a file before editing it. Never guess at existing code.
- Prefer `edit_file` (targeted find-and-replace) over `write_file` for existing files.
  Only use `write_file` for brand new files.
- Match the existing code style and conventions you observe in the project
  (naming, import style, error handling patterns).
- After making a change, verify it: at minimum run a Python import check
  or the project's test suite via `run_bash`.
- Explain your plan briefly before making edits, then execute it with tool calls.
- When you are done, give a short summary of what changed and how you verified it.
"""


def get_agent(provider: str, model_name: str):
    chat_model = init_chat_model(f"{provider}:{model_name}", temperature=0)
    agent = create_agent(
        model=chat_model,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=memory
    )
    return agent
