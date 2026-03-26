"""
app/services/memory_service.py

Hybrid conversation memory — no langchain.memory dependency.

Strategy:
- Keep last N raw messages verbatim (recent context)
- When message count exceeds MAX_RAW_MESSAGES, summarize the oldest
  half using the LLM and prepend as a system summary
- Summary + recent raw messages = full context passed to every LLM call

Storage: Redis session:{session_id} (60 min TTL)
"""

import os
import logging
from dotenv import load_dotenv

from langchain_community.chat_message_histories import ChatMessageHistory
from app.services.rag_cache import _safe_get, _safe_set, TTL_SESSION, delete_session

load_dotenv()
logger = logging.getLogger(__name__)

MAX_RAW_MESSAGES = 10   # keep last 10 messages (5 turns) verbatim
                         # beyond this, oldest messages get summarized


def _get_llm():
    from langchain_openai import AzureChatOpenAI
    return AzureChatOpenAI(
        azure_endpoint   = os.getenv("AZURE_LLM_ENDPOINT"),
        api_key          = os.getenv("AZURE_OPENAI_LLM_KEY"),
        azure_deployment = os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI"),
        api_version      = os.getenv("AZURE_LLM_API_VERSION", "2024-02-01"),
        temperature      = 0,
    )


def _summarize(messages: list[dict], existing_summary: str = "") -> str:
    """
    Summarize a list of {role, content} messages into a compact context string.
    Incorporates any existing summary to maintain continuity.
    """
    try:
        llm = _get_llm()
        conversation = "\n".join(
            f"{'User' if m['role'] == 'user' else 'CiteRAG'}: {m['content'][:300]}"
            for m in messages
        )
        prior = f"Prior context:\n{existing_summary}\n\n" if existing_summary else ""
        prompt = (
            f"{prior}Summarize this conversation in 3-5 sentences, "
            f"capturing key topics, questions asked, and answers given. "
            f"Be concise.\n\nConversation:\n{conversation}"
        )
        result = llm.invoke(prompt)
        return result.content.strip()
    except Exception as e:
        logger.warning(f"[memory] Summarization failed: {e}")
        return existing_summary


class HybridMemory:
    """
    Hybrid memory — recent raw messages + rolling LLM summary of older messages.
    Tracks first message explicitly so it's never lost to summarization.
    """

    def __init__(self, session_id: str):
        self.session_id    = session_id
        self.summary       = ""
        self.messages      = []   # list of {role, content}
        self.first_message = ""   # always preserved — never summarized

    def add_exchange(self, user_msg: str, assistant_msg: str):
        """Add a user/assistant exchange and compress if needed."""
        # Track the very first user message — never overwrite
        if not self.first_message:
            self.first_message = user_msg

        self.messages.append({"role": "user",      "content": user_msg})
        self.messages.append({"role": "assistant",  "content": assistant_msg})

        # Compress oldest messages into summary when limit exceeded
        if len(self.messages) > MAX_RAW_MESSAGES:
            split        = len(self.messages) - MAX_RAW_MESSAGES
            to_summarize = self.messages[:split]
            self.summary = _summarize(to_summarize, self.summary)
            self.messages = self.messages[split:]
            logger.info(
                f"[memory] Compressed {split} messages into summary "
                f"for session {self.session_id}"
            )

    def to_history(self) -> list[dict]:
        """
        Return chat_history list for passing to generate_answer().
        Order: system context (summary + first message reminder) → recent raw messages.
        """
        history = []

        # Build system context — summary + first message anchor
        context_parts = []
        if self.first_message:
            context_parts.append(f"The user's very first message in this conversation was: \"{self.first_message}\"")
        if self.summary:
            context_parts.append(f"Summary of earlier conversation:\n{self.summary}")

        if context_parts:
            history.append({
                "role":    "system",
                "content": "\n\n".join(context_parts),
            })

        # Add recent raw messages in chronological order
        history.extend(self.messages)
        return history

    def to_dict(self) -> dict:
        return {
            "session_id":    self.session_id,
            "summary":       self.summary,
            "messages":      self.messages,
            "first_message": self.first_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HybridMemory":
        mem               = cls(data["session_id"])
        mem.summary       = data.get("summary", "")
        mem.messages      = data.get("messages", [])
        mem.first_message = data.get("first_message", "")
        # Backfill first_message from messages if missing
        if not mem.first_message and mem.messages:
            first_user = next(
                (m["content"] for m in mem.messages if m.get("role") == "user"), ""
            )
            mem.first_message = first_user
        return mem


# ── Public API ────────────────────────────────────────────────────────────────

def get_memory(session_id: str) -> HybridMemory:
    """Load memory from Redis. Returns fresh memory if not found."""
    key  = f"session:{session_id}"
    data = _safe_get(key)
    if data and "messages" in data:
        mem = HybridMemory.from_dict(data)
        logger.info(
            f"[memory] Loaded session {session_id} — "
            f"{len(mem.messages)} messages, summary={'yes' if mem.summary else 'no'}"
        )
        return mem

    logger.info(f"[memory] No session found for {session_id} — starting fresh")
    return HybridMemory(session_id)


def save_memory(session_id: str, memory: HybridMemory) -> None:
    """Serialize memory to Redis with 60 min TTL."""
    try:
        key  = f"session:{session_id}"
        data = memory.to_dict()
        _safe_set(key, data, TTL_SESSION)
        logger.info(
            f"[memory] Saved session {session_id} — "
            f"{len(memory.messages)} messages, summary={'yes' if memory.summary else 'no'}"
        )
    except Exception as e:
        logger.error(f"[memory] Save failed for {session_id}: {e}")


def clear_memory(session_id: str) -> None:
    """Delete memory for a session (on New Chat)."""
    delete_session(session_id)
    logger.info(f"[memory] Cleared session {session_id}")