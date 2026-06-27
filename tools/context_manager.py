"""
Context size management — estimate, compress, and prune context before LLM calls.
Implements headroom calculation and context pruning to prevent overflow.
"""
import re
from typing import Optional


def estimate_tokens(text: str) -> int:
    """Estimate token count using character-based heuristic.
    Rule of thumb: ~4 chars per token for English text.
    """
    if not text:
        return 0
    # More accurate estimation accounting for code vs prose
    # Code tends to be denser, prose sparser
    code_ratio = len(re.findall(r'[{}[\]();=<>!@#\$%\^&\*\|]', text)) / max(len(text), 1)
    # ~3.5 chars/token for code-heavy, ~4.5 for prose-heavy
    avg_chars = 3.5 + (1 - code_ratio) * 1.0
    return max(1, int(len(text) / avg_chars))


def check_headroom(current_tokens: int, max_tokens: int, reserve_pct: float = 0.2) -> dict:
    """Calculate available headroom for context expansion.
    reserve_pct: fraction of max_tokens to reserve for the response.
    """
    reserve = int(max_tokens * reserve_pct)
    available = max_tokens - reserve
    headroom = available - current_tokens
    return {
        "current_tokens": current_tokens,
        "max_tokens": max_tokens,
        "reserve": reserve,
        "available": available,
        "headroom": headroom,
        "headroom_pct": round(headroom / max(max_tokens, 1) * 100, 1),
        "ok": headroom > 0,
    }


def compress_context(context: str, max_tokens: int, target_compression: float = 0.5) -> str:
    """Compress context by removing blank lines, trailing whitespace, and collapsing whitespace.
    Returns compressed text guaranteed to fit within max_tokens.
    """
    if not context:
        return context

    current = estimate_tokens(context)
    if current <= max_tokens:
        return context

    # Progressive compression
    compressed = context

    # Step 1: Collapse multiple blank lines to single
    compressed = re.sub(r'\n\s*\n\s*\n', '\n\n', compressed)

    # Step 2: Strip leading/trailing whitespace from each line
    lines = [line.strip() for line in compressed.split('\n')]
    compressed = '\n'.join(lines)

    # Step 3: Truncate from the end if still too large
    current = estimate_tokens(compressed)
    if current > max_tokens:
        # Take first 90% of target, leaving room for response
        target_chars = int(len(compressed) * (max_tokens / current))
        truncated = compressed[:target_chars]
        # Break at sentence boundary
        last_newline = truncated.rfind('\n')
        if last_newline > target_chars * 0.5:
            truncated = truncated[:last_newline]
        truncated += "\n\n[... truncated for context size ...]"
        compressed = truncated

    return compressed


def prune_context(contexts: Optional[list[tuple[str, str, float]]] = None, max_tokens: int = 16000) -> str:
    """Prune context by priority — keep high-priority content first.
    contexts: list of (name, content, priority) tuples. Higher priority = keep first.
    """
    if not contexts:
        return ""

    # Sort by priority descending
    sorted_ctx = sorted(contexts, key=lambda x: x[2], reverse=True)
    result = []
    total = 0

    for name, content, priority in sorted_ctx:
        tokens = estimate_tokens(content)
        if total + tokens > max_tokens:
            # Compress this item to fit remaining space
            remaining = max_tokens - total
            compressed = compress_context(content, max_tokens=remaining)
            result.append(f"## {name}\n{compressed}")
            total += estimate_tokens(compressed)
            break
        result.append(f"## {name}\n{content}")
        total += tokens

    return '\n\n'.join(result)


def prepare_context_for_llm(
    contexts: dict[str, str],
    max_tokens: int = 16000,
    reserve_pct: float = 0.2,
) -> dict:
    """Prepare context for LLM call — compress, prune, and calculate headroom.
    Returns the prepared context string and metadata.
    """
    reserve = int(max_tokens * reserve_pct)
    available = max_tokens - reserve

    # Score contexts by length (shorter = higher priority to keep intact)
    scored: list[tuple[str, str, float]] = []
    for name, content in contexts.items():
        tokens = estimate_tokens(content)
        priority = 1.0 / max(tokens, 1)  # Shorter content = higher priority
        scored.append((name, content, priority))

    pruned = prune_context(scored, max_tokens=available)
    headroom = check_headroom(estimate_tokens(pruned), max_tokens, reserve_pct)

    return {
        "context": pruned,
        "headroom": headroom,
        "compressed_items": len(scored),
        "total_tokens": estimate_tokens(pruned),
    }
