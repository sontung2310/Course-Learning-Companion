"""Shared helpers for agent orchestration (formatting, parsing, cache normalization)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def format_chat_history(messages: List[Dict[str, Any]]) -> str:
    """Format message list as readable chat history for prompts."""
    if not messages:
        return "No previous conversation."
    lines = []
    for m in messages:
        role = (m.get("role") or "user").lower()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {content}")
    return "\n".join(lines) if lines else "No previous conversation."


def format_retrieved_context(chunks: list[Dict[str, Any]]) -> str:
    """Format retrieved chunks for the groundedness checker."""
    parts = []
    for i, chunk in enumerate(chunks, 1):
        doc = chunk.get("document", "")
        meta = chunk.get("metadata", {}) or {}
        parts.append(
            f"[Segment {i}]\n"
            f"Content: {doc}\n"
            f"Metadata: {json.dumps(meta, default=str)}\n"
        )
    return "\n".join(parts) if parts else "(No segments retrieved)"


def parse_rag_decision_result(raw: str) -> Dict[str, Any]:
    """Extract JSON from RAG decision agent output. Default to use_rag=True if unparseable (safe: run RAG)."""
    text = raw.strip()
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        out = json.loads(text[start : i + 1])
                        use_rag = out.get("use_rag", True)
                        if not isinstance(use_rag, bool):
                            use_rag = str(use_rag).strip().lower() in ("true", "1", "yes")
                        return {"use_rag": use_rag}
                    except json.JSONDecodeError:
                        break
    lower = text.lower()
    if '"use_rag": false' in lower or "'use_rag': false" in lower:
        return {"use_rag": False}
    return {"use_rag": True}


def parse_groundedness_result(raw: str) -> Dict[str, str]:
    """Extract JSON from groundedness checker output; default to UNSUPPORTED if unparseable."""
    text = raw.strip()
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    u = text.upper()
    if "UNSUPPORTED" in u:
        return {"status": "UNSUPPORTED", "reason": text[:200] or "Could not parse checker output"}
    if "SUPPORTED" in u:
        return {"status": "SUPPORTED", "reason": text[:200]}
    return {"status": "UNSUPPORTED", "reason": text[:200] or "Could not parse checker output"}


def normalize_semantic_cache_hit(raw: Any) -> Optional[Dict[str, Any]]:
    """Turn Redis semantic-cache values into ``{response, use_rag}`` for the orchestrator.

    LiteLLM may return our ``json.dumps`` payload as a dict, or (if mixed with other
    writers) OpenAI-style ``choices`` / ``content`` shapes. Returns ``None`` if no
    usable assistant text is found so callers can fall through to a real generation.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            raw = json.loads(s)
        except json.JSONDecodeError:
            return {"response": raw, "use_rag": None}
    if not isinstance(raw, dict):
        return {"response": str(raw), "use_rag": None}

    use_rag = raw.get("use_rag")

    resp = raw.get("response")
    if resp is not None:
        text = resp if isinstance(resp, str) else str(resp)
        if text.strip():
            return {"response": text, "use_rag": use_rag}

    choices = raw.get("choices")
    if isinstance(choices, list) and choices:
        msg = (choices[0] or {}).get("message") or {}
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return {"response": content, "use_rag": use_rag}

    content = raw.get("content")
    if isinstance(content, str) and content.strip():
        return {"response": content, "use_rag": use_rag}

    return None
