"""Text fallback on the OpenAI-compatible Grok chat API. Voice is the primary interface."""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from app.tools import CHAT_TOOLS, dispatch_tool
from app.voice import INSTRUCTIONS, ROOT, api_key

load_dotenv(ROOT / ".env")


def client() -> OpenAI:
    return OpenAI(api_key=api_key(), base_url=os.getenv("XAI_BASE_URL", "https://api.x.ai/v1"))


def complete(user_text: str, messages: list[dict[str, Any]] | None = None) -> str:
    model = os.getenv("XAI_MODEL", "grok-4")
    if messages is None:
        messages = [
            {"role": "system", "content": INSTRUCTIONS},
        ]
    messages.append({"role": "user", "content": user_text})
    grok = client()
    for _ in range(8):
        response = grok.chat.completions.create(
            model=model,
            messages=messages,
            tools=CHAT_TOOLS,
        )
        choice = response.choices[0]
        messages.append(choice.message.to_dict())
        tool_calls = choice.message.tool_calls or []
        if not tool_calls:
            return choice.message.content or ""
        for call in tool_calls:
            result = dispatch_tool(call.function.name, call.function.arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result),
                }
            )
    return "Stopped after too many tool rounds."


def main() -> None:
    print("Otto text fallback. Voice is python -m app. Ctrl-D to quit.")
    conversation: list[dict[str, Any]] = [
        {"role": "system", "content": INSTRUCTIONS},
    ]
    while True:
        try:
            line = input("crew> ").strip()
        except EOFError:
            print()
            return
        if not line:
            continue
        print(complete(line, messages=conversation))


if __name__ == "__main__":
    main()
