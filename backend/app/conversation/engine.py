import json
from collections.abc import AsyncIterator
from typing import Any

from app.ai.base import LLMProvider
from app.conversation.context import ConversationContext
from app.conversation.prompt import build_system_prompt
from app.domain.profile import DomainProfile
from app.tools.registry import ToolRegistry


class ConversationEngine:
    """Domain-agnostic turn runner: prompt from profile -> LLM -> (tool loop) -> streamed text.

    Pure with respect to storage: callers pass history in and persist results themselves.
    """

    def __init__(self, llm: LLMProvider, tools: ToolRegistry | None = None, max_tool_rounds: int = 4):
        self.llm = llm
        self.tools = tools or ToolRegistry()
        self.max_tool_rounds = max_tool_rounds

    async def run_turn(
        self,
        profile: DomainProfile,
        ctx: ConversationContext,
        history: list[dict[str, Any]],
        user_text: str,
    ) -> AsyncIterator[str]:
        system = build_system_prompt(profile, ctx)
        tool_defs = self.tools.definitions_for(profile)
        messages = [*history, {"role": "user", "content": user_text}]

        for _ in range(self.max_tool_rounds + 1):
            text_parts: list[str] = []
            calls = []
            async for event in self.llm.stream(system, messages, tool_defs):
                if event.type == "text":
                    text_parts.append(event.text)
                    yield event.text
                else:
                    calls.append(event)
            if not calls:
                return

            blocks: list[dict[str, Any]] = []
            if "".join(text_parts).strip():
                blocks.append({"type": "text", "text": "".join(text_parts)})
            blocks += [
                {"type": "tool_use", "id": c.tool_id, "name": c.tool_name, "input": c.tool_input} for c in calls
            ]
            messages.append({"role": "assistant", "content": blocks})

            results = []
            for call in calls:
                output, is_error = await self.tools.execute(call.tool_name, ctx, call.tool_input)
                ctx.last_action = call.tool_name
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.tool_id,
                        "content": json.dumps(output),
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "user", "content": results})
