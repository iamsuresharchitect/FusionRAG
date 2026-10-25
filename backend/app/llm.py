"""Answer generation with Claude via the Anthropic API (streaming)."""
from anthropic import Anthropic

from . import config

SYSTEM_PROMPT = """You are a precise assistant that answers questions using ONLY the context passages supplied.

Rules:
- Base every statement on the context. Cite sources inline with their number in square brackets, e.g. [1] or [2][4].
- If the context does not contain the answer, say clearly that the uploaded documents do not cover it. Do not guess.
- Be concise and well structured. Use short paragraphs or bullet lists; use markdown tables when comparing items.
- Answer in the same language the user asks in."""

_client: Anthropic | None = None


def client() -> Anthropic:
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in backend/.env")
        _client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def build_context(hits: list[dict]) -> str:
    blocks = []
    for n, h in enumerate(hits, 1):
        where = h["doc_name"] + (f", page {h['page']}" if h.get("page") else "")
        blocks.append(f'<source id="{n}" from="{where}">\n{h["text"]}\n</source>')
    return "\n\n".join(blocks)


def _sanitize_history(history: list[dict], max_turns: int = 6) -> list[dict]:
    """Keep the last few turns, alternating user/assistant, starting with user."""
    msgs = [{"role": m["role"], "content": str(m["content"])[:4000]}
            for m in history if m.get("role") in ("user", "assistant") and m.get("content")]
    msgs = msgs[-max_turns:]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    merged: list[dict] = []
    for m in msgs:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] += "\n\n" + m["content"]
        else:
            merged.append(m)
    if merged and merged[-1]["role"] == "user":  # the new question will be the next user turn
        merged.pop()
    return merged


def stream_answer(question: str, hits: list[dict], history: list[dict] | None = None):
    messages = _sanitize_history(history or [])
    messages.append({
        "role": "user",
        "content": f"<context>\n{build_context(hits)}\n</context>\n\nQuestion: {question}",
    })
    with client().messages.stream(
        model=config.CLAUDE_MODEL,
        max_tokens=config.MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text
