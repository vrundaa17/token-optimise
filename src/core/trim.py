import tiktoken
from config import settings

_encoder = tiktoken.get_encoding("cl100k_base")

def count_tokens(text):
    return len(_encoder.encode(str(text)))

MAX_RESPONSE_TOKENS = settings.max_response_tokens
import json

def _is_json(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith(("{", "["))

def trim_text_response(text: str, max_tokens: int = MAX_RESPONSE_TOKENS) -> tuple[str, int, int]:
    original_tokens = count_tokens(text)
    
    if original_tokens <= max_tokens:
        return text, original_tokens, original_tokens
    

    # JSON response — truncate keys/values rather than raw cut
    if _is_json(text):
        try:
            parsed = json.loads(text)
            # if it's a list, just take first N items
            if isinstance(parsed, list) and len(parsed) > 10:
                parsed = parsed[:10]
                trimmed = json.dumps(parsed) + "\n\n[Trimmed: showing 10 of original items]"
                return trimmed, original_tokens, count_tokens(trimmed)
        except Exception:
            pass
        # fallback — return as-is, still record actual token count
        return text, original_tokens, original_tokens
    
    # plain text — cut at sentence boundary
    char_limit = max_tokens * 4
    trimmed = text[:char_limit]
    last_period = trimmed.rfind('.')
    if last_period > char_limit * 0.7:
        trimmed = trimmed[:last_period + 1]
    
    trimmed += f"\n\n[Response trimmed: {original_tokens} → {count_tokens(trimmed)} tokens]"
    return trimmed, original_tokens, count_tokens(trimmed)