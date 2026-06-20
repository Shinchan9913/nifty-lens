"""LLM provider config — one OpenAI-compatible client, swappable by env vars.

Groq, OpenRouter, GitHub Models and Google AI Studio all speak the OpenAI
"chat completions" wire format, so we target that one interface and choose the
provider purely through environment variables (set them in the root .env):

    # Groq (default — fast, reliable tool calling, free)
    LLM_API_KEY=gsk_...
    LLM_BASE_URL=https://api.groq.com/openai/v1
    LLM_MODEL=llama-3.3-70b-versatile

    # OpenRouter (free reasoning models -> the "thinking" panel lights up)
    # LLM_API_KEY=sk-or-...
    # LLM_BASE_URL=https://openrouter.ai/api/v1
    # LLM_MODEL=deepseek/deepseek-r1:free

    # Google AI Studio (huge free daily quota)
    # LLM_API_KEY=AIza...
    # LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
    # LLM_MODEL=gemini-2.5-flash

    # GitHub Models (free with your GitHub token)
    # LLM_API_KEY=github_pat_...
    # LLM_BASE_URL=https://models.github.ai/inference
    # LLM_MODEL=openai/gpt-4o
"""
import os

from openai import AsyncOpenAI

DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
API_KEY = os.getenv("LLM_API_KEY", "")


def get_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=API_KEY, base_url=DEFAULT_BASE_URL)


def to_openai_tool(tool: dict) -> dict:
    """Convert our neutral {name, description, input_schema} tool spec into the
    OpenAI function-calling shape {type, function:{name, description, parameters}}."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }
