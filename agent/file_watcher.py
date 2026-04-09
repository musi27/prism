"""File watcher agent — continuously running, raw Anthropic API, no LangChain.

Watches a folder for new files, reads them, summarises with an LLM,
and writes summary files alongside the originals. Runs until Ctrl+C.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
import prism

from agent.file_watcher_tools import (
    watch_folder, read_file, write_summary,
    TOOLS_SCHEMA, TOOL_MAP, WATCH_PATH,
)

SYSTEM_PROMPT = (
    "You are a file watcher assistant. You continuously watch a folder for new files. "
    "When new files appear, read each one and write a short plain English summary of its "
    "contents to a summary file next to the original. Process one file at a time. "
    "After processing all new files, watch the folder again."
)


def process_new_files(client, new_files: list[str]):
    """Use the LLM to read and summarise each new file."""
    for filename in new_files:
        filepath = os.path.join(WATCH_PATH, filename)
        print(f"\n  New file: {filename}")

        messages = [{"role": "user", "content": (
            f"A new file appeared: {filepath}\n"
            f"Read it with read_file, then write a short summary with write_summary."
        )}]

        while True:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                system=SYSTEM_PROMPT,
                tools=TOOLS_SCHEMA,
                messages=messages,
            )

            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for block in assistant_content:
                if block.type == "tool_use":
                    name = block.name
                    args = block.input
                    print(f"  -> {name}({args})")

                    try:
                        result = TOOL_MAP[name](**args)
                    except Exception as e:
                        result = f"Error: {e}"

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })

            if tool_results:
                messages.append({"role": "user", "content": tool_results})
                continue

            if response.stop_reason == "end_turn":
                break

            messages.append({"role": "user", "content": "Continue."})


def main():
    prism.configure(
        agent_id="file-watcher-v1",
        log_path="./logs",
        require_approval_for=["write_summary"],
        tools=["watch_folder", "read_file", "write_summary"],
    )

    os.makedirs(WATCH_PATH, exist_ok=True)
    client = anthropic.Anthropic()

    print(f"File Watcher Agent — watching {WATCH_PATH}")
    print("Drop files into the folder. Press Ctrl+C to stop.\n")

    while True:
        result = watch_folder(WATCH_PATH)
        if result:
            new_files = [f.strip() for f in result.split(",") if f.strip()]
            process_new_files(client, new_files)
        else:
            print("  ... watching", end="\r")
        time.sleep(10)


if __name__ == "__main__":
    main()
