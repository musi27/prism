import os
import sys
import warnings

# Suppress LangChain's Pydantic V1 warning on Python 3.14+
warnings.filterwarnings("ignore", message="Core Pydantic V1")

# Ensure imports work whether run as `python agent/agent.py` or `python -m agent.agent`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

import prism
from agent.research_tools import search_web, read_page, write_to_sheet

SYSTEM_PROMPT = (
    "You are a research assistant. Today's date is {today}. "
    "For each company provided, find their website, "
    "write a two-sentence summary of what they do, estimate their size, identify any "
    "news from the last 3 months, and note the most relevant person to contact. "
    "Write your findings to the spreadsheet."
)

TEST_COMPANIES = ["Stripe", "Notion", "Linear"]

TOOLS = [search_web, read_page, write_to_sheet]
TOOL_MAP = {t.name: t for t in TOOLS}


def run_agent(input_text: str) -> str:
    llm = ChatAnthropic(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
    ).bind_tools(TOOLS)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT.format(today=date.today().isoformat())),
        HumanMessage(content=input_text),
    ]

    while True:
        response = llm.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            return response.content

        for tool_call in response.tool_calls:
            name = tool_call["name"]
            args = tool_call["args"]
            print(f"  -> {name}({args})")

            try:
                result = TOOL_MAP[name].invoke(args)
            except Exception as e:
                result = f"Error: {e}"

            messages.append(ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
            ))


def main():
    prism.configure(agent_id="prospect-researcher-v1", log_path="./logs", require_approval_for=["write_to_sheet"])
    companies_str = ", ".join(TEST_COMPANIES)
    print(f"Researching: {companies_str}\n")

    result = run_agent(
        f"Research these companies and write findings to the spreadsheet: {companies_str}"
    )

    print("\n--- Agent Output ---")
    print(result)


if __name__ == "__main__":
    main()
