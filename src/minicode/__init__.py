# src/minicode/__init__.py

import uuid

from dotenv import load_dotenv


from minicode.agent import build_agent, run_task
from minicode.rich_text_service import print_banner, print_goodbye, read_task


load_dotenv()


def main():
    agent = build_agent()
    thread_id = str(uuid.uuid4())
    print_banner(thread_id)

    while True:
        task = read_task()
        if not task or task.lower() in ("exit", "quit"):
            break
        run_task(agent, task, thread_id)

    print_goodbye()


if __name__ == "__main__":
    main()
