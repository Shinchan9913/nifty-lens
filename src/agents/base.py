"""Base agent: a streaming, OpenAI-compatible tool-use loop wired to the event bus.

An agent is just a loop around one chat-completion call:
  1. send the conversation + tool definitions
  2. stream back reasoning (-> "thinking"), text (-> "text"), and/or tool calls
  3. if it asked for tools, run them and append the results
  4. repeat until it stops asking for tools; return the final text

Every step is emitted to the EventBus so the UI can show it live. Tool calls
within a turn run concurrently (asyncio.gather), so when the orchestrator
consults several specialists at once they genuinely work in parallel.

Note on the stream format: OpenAI-style APIs deliver tool calls in *fragments* —
the function name once, then the JSON arguments in small pieces, each tagged with
an `index`. We accumulate fragments per index and only json.loads() at the end.
"""
import asyncio
import json

from .bus import EventBus
from .llm import DEFAULT_MODEL, to_openai_tool
from .tools import HANDLERS, TOOL_SCHEMAS, summarize_result


class Agent:
    def __init__(
        self,
        agent_id: str,
        name: str,
        emoji: str,
        color: str,
        role: str,
        system: str,
        tool_names: tuple[str, ...] = (),
        model: str | None = None,
        max_tokens: int = 4096,
        max_rounds: int = 8,
    ) -> None:
        self.id = agent_id
        self.name = name
        self.emoji = emoji
        self.color = color
        self.role = role
        self.system = system
        self.tool_names = tool_names
        self.model = model or DEFAULT_MODEL
        self.max_tokens = max_tokens
        self.max_rounds = max_rounds

    def _tools(self, extra_tools: list[dict] | None) -> list[dict]:
        specs = [TOOL_SCHEMAS[n] for n in self.tool_names]
        if extra_tools:
            specs.extend(extra_tools)
        return [to_openai_tool(s) for s in specs]

    async def run(
        self,
        client,
        bus: EventBus,
        task: str,
        extra_tools: list[dict] | None = None,
        extra_handlers: dict | None = None,
    ) -> str:
        """Run the agent to completion and return its final text answer."""
        tools = self._tools(extra_tools)
        handlers = {n: HANDLERS[n] for n in self.tool_names}
        if extra_handlers:
            handlers.update(extra_handlers)

        messages: list[dict] = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": task},
        ]
        await bus.emit("agent_status", agent=self.id, status="working")

        last_text = ""
        for _round in range(self.max_rounds):  # guard against runaway tool loops
            await bus.emit("agent_status", agent=self.id, status="thinking")
            text_parts: list[str] = []
            calls_acc: dict[int, dict] = {}  # index -> {id, name, args}

            create_kwargs = dict(
                model=self.model,
                messages=messages,
                stream=True,
                max_tokens=self.max_tokens,
            )
            if tools:
                create_kwargs["tools"] = tools
                # Free 70B models (e.g. Llama on Groq) garble *parallel* tool calls —
                # they fuse the function name with its JSON args, which the provider
                # then rejects. Forcing one tool call per turn trades simultaneity for
                # reliability. Frontier models handle parallel calls fine; flip this if
                # you point LLM_* at one.
                create_kwargs["parallel_tool_calls"] = False
            stream = await client.chat.completions.create(**create_kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta is None:
                    continue

                # Reasoning models (DeepSeek-R1, etc.) expose their chain of thought
                # under one of these field names — map it to our "thinking" stream.
                reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                if reasoning:
                    await bus.emit("thinking", agent=self.id, text=reasoning)

                if delta.content:
                    text_parts.append(delta.content)
                    await bus.emit("text", agent=self.id, text=delta.content)

                for tc in delta.tool_calls or []:
                    slot = calls_acc.setdefault(tc.index, {"id": None, "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments

            turn_text = "".join(text_parts).strip()
            if turn_text:
                last_text = turn_text

            calls = [calls_acc[i] for i in sorted(calls_acc)]

            assistant_msg: dict = {"role": "assistant", "content": turn_text or None}
            if calls:
                assistant_msg["tool_calls"] = [
                    {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["args"] or "{}"}}
                    for c in calls
                ]
            messages.append(assistant_msg)

            if not calls:
                break

            results = await asyncio.gather(*[self._run_tool(bus, handlers, c) for c in calls])
            messages.extend(results)

        await bus.emit("agent_status", agent=self.id, status="done")
        return last_text

    async def _run_tool(self, bus: EventBus, handlers: dict, call: dict) -> dict:
        name = call["name"]
        try:
            args = json.loads(call["args"] or "{}")
        except json.JSONDecodeError:
            args = {}
        await bus.emit("tool_call", agent=self.id, tool=name, input=args)

        handler = handlers.get(name)
        if handler is None:
            await bus.emit("tool_result", agent=self.id, tool=name, ok=False, summary="unknown tool")
            return {"role": "tool", "tool_call_id": call["id"], "content": f"Unknown tool {name}"}
        try:
            result = await handler(**args)
            await bus.emit("tool_result", agent=self.id, tool=name, ok=True, summary=summarize_result(result))
            return {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, default=str)}
        except Exception as exc:  # surface failures to both the model and the UI
            await bus.emit("tool_result", agent=self.id, tool=name, ok=False, summary=str(exc))
            return {"role": "tool", "tool_call_id": call["id"], "content": f"Error: {exc}"}
