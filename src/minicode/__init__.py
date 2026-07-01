import argparse
from agent import get_agent
from utils import render_completed_step, render_message_chunk
from dotenv import load_dotenv
import uuid

load_dotenv()

available_providers = ["deepseek"]

available_models = {
    "deepseek": ["deepseek-v4-flash"]
}


def main() -> None:
    print("Welcome to MiniCode CLI!")
    print("\nAvailable providers: ")
    for i, provider in enumerate(available_providers, start=1):
        print(f"{i} - {provider}")

    provider_choice_index = int(input("\n\nSelect a provider by number: ")) - 1

    selected_provider = available_providers[provider_choice_index]

    print(f"\nAvailable models for {selected_provider}: ")
    for i, model in enumerate(available_models.get(selected_provider, []), start=1):
        print(f"{i} - {model}")

    model_choice_index = int(input("\n\nSelect a model by number: ")) - 1

    selected_model = available_models.get(selected_provider, [])[model_choice_index]

    print(f"You selected: {selected_model}")

    agent = get_agent(selected_provider, selected_model)

    config = {
        "configurable": {
            "thread_id": str(uuid.uuid4())[:255],
        }
    }

    while True:
        user_input = input("\n\nEnter Prompt, type 'quit' to exit: ")
        if user_input.lower() == 'quit':
            break

        for mode, chunk in agent.stream({"messages": [{"role": "user", "content": user_input}]}, stream_mode=["messages", "updates"], config=config):
            if mode == "messages":
                token, metadata = chunk
                if metadata.get("langgraph_node") == "model":
                    render_message_chunk(token)
            elif mode == "updates":
                for source, update in chunk.items():
                    if source in ("model", "tools"):
                        render_completed_step(source, update["messages"][-1])
