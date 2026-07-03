"""
utils.py
--------
Two kinds of helpers live here:

1. safe_path() -- keeps every tool confined to the current directory.
2. handle_message_chunk() / handle_update_chunk() -- the logic for
   agent.py's streaming loop, one function per stream type, so the loop
   itself stays a clean two-line dispatch instead of inline if/elif logic.
"""

from minicode.rich_text_service import print_assistant_text, print_tool_call, print_tool_result

import os


class ToolError(Exception):
    """Raised when a tool can't complete safely. Message is shown to the LLM."""
    pass


def safe_path(relative_path: str) -> str:
    """Resolve relative_path against the current directory and make sure
    the result stays INSIDE it -- stops the agent from touching files
    outside the project, e.g. relative_path='../../etc/passwd'."""
    root = os.path.abspath(os.getcwd())
    full_path = os.path.abspath(os.path.join(root, relative_path))
    if not full_path.startswith(root + os.sep) and full_path != root:
        raise ToolError(f"Refused: '{relative_path}' resolves outside the project directory.")
    return full_path


def handle_message_chunk(token, metadata) -> None:
    """A 'messages' stream event -- a live token of assistant text."""
    if metadata.get("langgraph_node") == "model" and getattr(token, "text", None):
        print_assistant_text(token.text)


def handle_update_chunk(source: str, update: dict) -> None:
    """An 'updates' stream event -- a completed tool call or tool result."""
    message = update["messages"][-1]
    if source == "model" and getattr(message, "tool_calls", None):
        for tool_call in message.tool_calls:
            print_tool_call(tool_call["name"], tool_call["args"])
    elif source == "tools":
        print_tool_result(str(message.content))
