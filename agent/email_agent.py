"""Email triage agent — raw Anthropic API, no LangChain.

Reads a mock inbox, categorises each email, and drafts replies.
Uses the Prism SDK for instrumentation.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
import prism

from agent.email_tools import (
    read_inbox, categorise_email, draft_reply,
    TOOLS_SCHEMA, TOOL_MAP, _categories, _drafts,
)

SYSTEM_PROMPT = (
    "You are an email triage assistant. Read the inbox, categorise every email "
    "(bug_report, feature_request, billing, general_inquiry, or urgent), "
    "then draft a short, professional reply to each one."
)


def run_agent():
    client = anthropic.Anthropic()

    messages = [{"role": "user", "content": "Triage my inbox. Read all emails, categorise each one, then draft a reply for every email."}]

    while True:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=SYSTEM_PROMPT,
            tools=TOOLS_SCHEMA,
            messages=messages,
        )

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Process any tool_use blocks regardless of stop_reason
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
            # Tools were called — feed results back and continue
            messages.append({"role": "user", "content": tool_results})
            continue

        # No tool calls in this response
        if response.stop_reason == "end_turn":
            # Model is done — extract final text
            for block in assistant_content:
                if hasattr(block, "text"):
                    return block.text
            return ""

        # stop_reason is "max_tokens" with no tool calls — model was cut off mid-text
        # Prompt it to continue
        messages.append({"role": "user", "content": "Continue."})


def main():
    prism.configure(
        agent_id="email-triage-v1",
        log_path="./logs",
        require_approval_for=["draft_reply"],
        tools=["read_inbox", "categorise_email", "draft_reply"],
    )

    print("Email Triage Agent\n")

    result = run_agent()

    print("\n--- Agent Output ---")
    print(result)

    print("\n--- Categories ---")
    for eid, cat in sorted(_categories.items()):
        print(f"  {eid}: {cat}")

    print("\n--- Drafts ---")
    for eid, draft in sorted(_drafts.items()):
        print(f"  {eid}: {draft[:80]}...")


if __name__ == "__main__":
    main()
