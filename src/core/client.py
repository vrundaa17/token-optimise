import litellm
from token_optimise.config import settings
import chromadb
import os, json
import logging

logger = logging.getLogger("token")

litellm.drop_params = True 
litellm.set_verbose = False

_chroma_client = None

def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        storage_dir = os.environ.get(
            "TOKEN_STORAGE_DIR",
            os.path.join(os.path.expanduser("~"), ".token_optimise", "storage")
        )
        chroma_path = os.path.join(storage_dir, "chroma_db")
        _chroma_client = chromadb.PersistentClient(path=chroma_path)
    return _chroma_client



# ------------------------------------------------------------------------------------------------------------------------------------------------------
# model list

_EXCLUDE_KEYWORDS = [
    "whisper", "guard", "embed", "tts", "audio",
    "image", "moderation", "rerank", "speech", "vision", "ft:", "container","realtime",
]

def _get_chat_models_for_provider(provider: str) -> list[str]:
    """Ask litellm to find all the available model """
    models = []
    for model_key, info in litellm.model_cost.items():
        if (
            info.get("litellm_provider") == provider
            and info.get("mode") == "chat"
            and not any(x in model_key.lower() for x in _EXCLUDE_KEYWORDS)
        ):
            prefixed = model_key if model_key.startswith(provider + "/") else f"{provider}/{model_key}"
            if prefixed not in models:
                models.append(prefixed)
    return models


def _get_model_list() -> list[str]:

    primary = os.environ.get("LLM_MODEL", "").strip()

    if not primary:
        primary = getattr(settings, "llm_model", "").strip()
    if not primary:
        raise RuntimeError(
            "No LLM model configured. Set LLM_MODEL in ~/.token_optimise/.env"
        )
    # If no prefix, try to detect provider from LiteLLM
    if "/" not in primary and primary:
        try:
            _, provider_detected, _, _ = litellm.get_llm_provider(primary)
            if provider_detected:
                primary = f"{provider_detected}/{primary}"
                logger.info(f"[LLM] auto-detected provider: {primary}")
        except Exception:
            logger.warning(
                f"[LLM] could not detect provider for '{primary}'. "
                f"Use full format e.g. 'openai/gpt-4o' or 'anthropic/claude-3-5-haiku-20241022'"
            )
        
    provider = primary.split("/")[0] if "/" in primary else ""

    raw_fallbacks = os.environ.get("LLM_FALLBACKS", getattr(settings, "llm_fallbacks", "")).strip()
    user_fallbacks = [m.strip() for m in raw_fallbacks.split(",") if m.strip()] if raw_fallbacks else []
    
    dynamic_fallbacks = _get_chat_models_for_provider(provider) if provider else []

    seen = set()
    ordered = []
    for m in [primary] + user_fallbacks + dynamic_fallbacks:
        if m and m not in seen and m not in _dead_models:
            seen.add(m)
            ordered.append(m)

    return ordered


# ------------------------------------------------------------------------------------------------------------------------------------------------------
# model error

_DEAD_PATTERNS = [
    "not found", "not available", "not accessible",
    "decommissioned", "deprecated", "does not exist",
    "no longer available", "invalid model", "model_not_found",
    "unknown model", "no such model",
]
_RETRY_PATTERNS = ["rate limit", "rate_limit", "429", "503", "502", "timeout", "connection"]

_dead_models: set = set()
_working_model: str | None = None


def _classify_error(err: str) -> str:
    err = err.lower()
    if any(p in err for p in _DEAD_PATTERNS):
        return "dead"
    if any(p in err for p in _RETRY_PATTERNS):
        return "retry"
    return "dead"


def _set_provider_keys():
    pairs = {
        "GROQ_API_KEY": getattr(settings, "groq_api_key", ""),
        "OPENAI_API_KEY": getattr(settings, "openai_api_key", ""),
        "ANTHROPIC_API_KEY": getattr(settings, "anthropic_api_key", ""),
        "DEEPSEEK_API_KEY": getattr(settings, "deepseek_api_key", ""),
    }
    for k, v in pairs.items():
        if v and not os.environ.get(k):
            os.environ[k] = v


_set_provider_keys()



# ------------------------------------------------------------------------------------------------------------------------------------------------------
# core call 

def _call_llm(messages: list, max_tokens: int = 200, temperature: float = 0) -> tuple:
    global _working_model
    ordered = _get_model_list()

    if _working_model and _working_model in ordered:
        ordered = [_working_model] + [m for m in ordered if m != _working_model]

    if not ordered:
        raise RuntimeError("No models available — check LLM_MODEL and your API key in ~/.token_optimise/.env")

    last_error = "no models available"
    for model in ordered:
        try:
            logger.info(f"[LLM] trying: {model}")
            resp = litellm.completion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            _working_model = model
            logger.info(f"[LLM] success: {model}")
            return resp, model

        except Exception as e:
            err_str = str(e)
            err_type = _classify_error(err_str)
            if err_type == "dead":
                logger.warning(f"[LLM] {model} dead: {err_str[:120]} — skipping")
                _dead_models.add(model)
                if _working_model == model:
                    _working_model = None
                last_error = err_str
                continue
            else:
                logger.warning(f"[LLM] {model} transient error: {err_str[:120]} — stopping")
                last_error = err_str
                break

    raise RuntimeError(f"All models exhausted. Last error: {last_error}")


# ------------------------------------------------------------------------------------------------------------------------------------------------------

def fill_args_llm(query, schema):
    props = schema.get("properties", {})
    required = schema.get("required", [])
    schema_summary = "\n".join([
        f"- {name} ({info.get('type', 'string')}) : {info.get('description', 'no desc')}"
        for name, info in props.items()
    ])

    prompt = (
        f"You are a tool argument filler. Given a tool schema and a user query, "
        f"return ONLY a valid JSON object with the correct arguments.\n"
        f"Tool parameters:\n{schema_summary}\n"
        f"Required fields: {required}\n"
        f"User query: \"{query}\"\n\n"
        f"Rules:\n"
        f"- Return ONLY a JSON object, no explanation, no markdown, no backticks\n"
        f"- If the task is to LIST or BROWSE files in a folder, the tool needed is list_directory and path must be a DIRECTORY.\n"
        f"- If the task is to READ file content, the tool needed is read_file and path must be a FILE.\n"
        f"- For file paths: NEVER use ~ or relative paths. Always expand to full absolute path.\n"
        f"- Home directory is: {os.path.expanduser('~')}\n"
        f"- Desktop is: {os.path.expanduser('~/Desktop')}\n"
        f"- Documents is: {os.path.expanduser('~/Documents')}\n"
        f"JSON:"
    )

    try:
        raw, model_used = _call_llm(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0,
        )
        usage = raw.usage
        logger.info(f"[LLM] fill_args | model={model_used} prompt={usage.prompt_tokens} completion={usage.completion_tokens}")

        response = raw.choices[0].message.content.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
            response = response.strip()

        args = json.loads(response)
        result = {k: v for k, v in args.items() if v is not None}
        result["_groq_usage"] = {           
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
        }
        return result

    except RuntimeError as e:
        logger.error(f"[LLM] fill_args_llm: all models failed: {e}")
        return {"_groq_error": str(e)}
    except json.JSONDecodeError as e:
        logger.warning(f"[LLM] failed to parse args JSON: {e}")
        return {"_groq_error": f"JSONDecodeError: {e}"}
    except Exception as e:
        logger.error(f"[LLM] fill_args_llm failed: {e}")
        return {"_groq_error": str(e)}


# ------------------------------------------------------------------------------------------------------------------------------------------------------

def expand_query(query: str, tool_descriptions: list[dict]) -> tuple[str, int, int]:
    if not tool_descriptions:
        return query, 0, 0

    tools_text = "\n".join(
        f"- {t['function']['name']}: {t['function'].get('description', '')}"
        for t in tool_descriptions
    )

    try:
        resp, model_used = _call_llm(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a query rewriter. Rewrite the user query using the exact "
                        "terminology of the available tools. Output ONLY the rewritten query. "
                        "Important: 'list files', 'show files', 'browse folder' means list_directory. "
                        "'read', 'open', 'get contents of a file' means read_file."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Tools:\n{tools_text}\n\nUser query: {query}\n\nRewritten query:",
                },
            ],
            max_tokens=60,
            temperature=0.0,
        )
        usage = resp.usage
        rewritten = resp.choices[0].message.content.strip()
        return (rewritten if rewritten else query, usage.prompt_tokens, usage.completion_tokens)

    except Exception as e:
        logger.warning(f"[EXPAND_QUERY] failed: {e}")
        return query, 0, 0
    
    