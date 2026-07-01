def render_message_chunk(token) -> None:
    """Print the assistant's text as it's generated, token by token."""

    if getattr(token, "text", None):
        print(token.text, end="", flush=True)


def render_completed_step(source: str, message) -> None:
    """Print a tool call the moment it's decided, or a tool's result the
    moment it finishes. These arrive whole (not token-streamed), since a
    tool call/result isn't generated incrementally the way text is."""

    if source == "model" and getattr(message, "tool_calls", None):
        for tc in message.tool_calls:
            print(f"\n\n[tool_call] {tc['name']}({tc['args']})\n", flush=True)
    elif source == "tools":
        content = str(message.content)
        preview = content if len(content) < 500 else content[:500] + "..."
        print(f"[tool_result] {preview}\n", flush=True)
