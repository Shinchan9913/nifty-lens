"""Multi-agent market-analysis layer (OpenAI-compatible LLM + ClickHouse tools).

Importing this package loads the project-root .env (the gitignored one that holds
your real keys) so the LLM_* settings and Groww keys are available to the agents.
See llm.py for the provider/model configuration.
"""
from pathlib import Path

from dotenv import load_dotenv

# This file is <root>/src/agents/__init__.py, so the repo root is two levels up.
_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ROOT_ENV)
