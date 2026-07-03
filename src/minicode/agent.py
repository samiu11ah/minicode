"""
agent.py
--------
Builds the model and the agent, and runs one task at a time, streaming
output live as it works.
"""

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver

from minicode.constants import MODEL, SYSTEM_PROMPT
from minicode.tools import TOOLS
from minicode.utils import handle_message_chunk, handle_update_chunk


def build_agent():
    """Create the model, wrap it with our tools and system prompt, and
    give it memory via a checkpointer."""
    model = init_chat_model(MODEL, temperature=0)
    checkpointer = InMemorySaver()
    return create_agent(model=model, tools=TOOLS, system_prompt=SYSTEM_PROMPT, checkpointer=checkpointer)


def run_task(agent, task: str, thread_id: str) -> None:
    """Run one task and stream the output live: assistant text word-by-
    word, tool calls/results the moment each one happens."""
    config = {"configurable": {"thread_id": thread_id}}

    for mode, chunk in agent.stream(
        {"messages": [{"role": "user", "content": task}]},
        config=config,
        stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            token, metadata = chunk
            handle_message_chunk(token, metadata)
        elif mode == "updates":
            for source, update in chunk.items():
                handle_update_chunk(source, update)

    print()
