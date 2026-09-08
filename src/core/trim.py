import tiktoken
import json
from token_optimise.config import settings

_encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(text) -> int:
    return len(_encoder.encode(str(text)))


MAX_RESPONSE_TOKENS = settings.max_response_tokens


def _is_json(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith(("{", "["))


def trim_text_response(text: str, max_tokens: int = MAX_RESPONSE_TOKENS) -> tuple:
    """Returns (trimmed_text, original_token_count, final_token_count)."""
    original_tokens = count_tokens(text)

    if original_tokens <= max_tokens:
        return text, original_tokens, original_tokens

    if _is_json(text):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list) and len(parsed) > 10:
                parsed = parsed[:10]
                trimmed = json.dumps(parsed) + "\n\n[Trimmed: showing 10 of original items]"
                trimmed_tokens = count_tokens(trimmed)
                if trimmed_tokens <= max_tokens:
                    return trimmed, original_tokens, trimmed_tokens
            elif isinstance(parsed, dict) and len(parsed) > 20:
                # Keep first 20 keys
                reduced = dict(list(parsed.items())[:20])
                trimmed = json.dumps(reduced) + "\n\n[Trimmed: showing 20 of original keys]"
                trimmed_tokens = count_tokens(trimmed)
                if trimmed_tokens <= max_tokens:
                    return trimmed, original_tokens, trimmed_tokens
        except Exception:
            pass
        # JSON could not be reduced enough  fall through to plain-text trim

    # Plain-text trim at sentence boundary
    char_limit = max_tokens * 4
    trimmed = text[:char_limit]
    last_period = trimmed.rfind(".")
    if last_period > char_limit * 0.7:
        trimmed = trimmed[: last_period + 1]

    trimmed += f"\n\n[Response trimmed: {original_tokens} | {count_tokens(trimmed)} tokens]"
    return trimmed, original_tokens, count_tokens(trimmed)