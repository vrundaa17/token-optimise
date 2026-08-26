from groq import Groq
from config import settings,PROJECT_ROOT
import chromadb
import os,json
import logging

logger = logging.getLogger("token")

_groq_client = Groq(api_key=settings.groq_api_key)
CHROMA_PATH = os.path.join(PROJECT_ROOT, "storage", "chroma_db")
_chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

def fill_args_llm(query,schema):
    props = schema["properties"]
    required = schema.get("required", [])
    schema_summary="\n".join([
        f"- {name} ({info.get('type','string')}) : {info.get('description','no desc')}"
        for name,info in props.items()
    ])
    
    prompt = f"""You are a tool argument filler. Given a tool schema and a user query, return ONLY a valid JSON object with the correct arguments.
        Tool parameters: {schema_summary}
        Required fields: {required}
        User query: "{query}"

        Rules:
        - Return ONLY a JSON object, no explanation, no markdown, no backticks
        - For file paths: NEVER use ~ or relative paths. Always expand to full absolute path.
        - Home directory is: {os.path.expanduser('~')}
        - Desktop is: {os.path.expanduser('~/Desktop')}
        - Documents is: {os.path.expanduser('~/Documents')}
        - If user says "Desktop", use: {os.path.expanduser('~/Desktop')}
        - If user says "home", use: {os.path.expanduser('~')}
        - Example: "file on Desktop" → "{os.path.expanduser('~/Desktop')}/filename.pdf"
        JSON:
    """
        
    
    try:
        raw = _groq_client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages = [{"role":"user","content":prompt}],
            temperature=0,
            max_tokens=settings.max_response_tokens,
        ) 
        usage = raw.usage
        logger.info(f"[GROQ] fill_args | prompt_tokens={usage.prompt_tokens} completion_tokens={usage.completion_tokens}")
        response = raw.choices[0].message.content.strip()
        args = json.loads(response)
        result = {k: v for k, v in args.items() if v is not None}
        result["_groq_usage"] = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens
        }
        return result
    
    except json.JSONDecodeError as e:
        logger.warning(f"[GROQ] failed to parse args JSON: {e} — trying schema defaults")
        try:
            required = schema.get("required", [])
            props = schema.get("properties", {})
            fallback = {}
            for field in required:
                field_type = props.get(field, {}).get("type", "string")
                fallback[field] = "" if field_type == "string" else None
            logger.info(f"[GROQ] fallback args: {fallback}")
            return fallback
        except Exception:
            return {}
    except Exception as e:
        logger.warning(f"[GROQ] fill_args_llm failed: {e}")
        return {"_groq_error": str(e)}



def expand_query(query: str, tool_descriptions: list[dict]) -> str:
    
    capped = tool_descriptions[:10]
    tools_text = "\n".join(
        f"- {t['function']['name']}: {t['function'].get('description', '')}"
        for t in capped
    )
    
    try:
        resp = _groq_client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a query rewriter. Given a user query and a list of available tools, "
                        "rewrite the query using the exact terminology and phrasing that best matches "
                        "the tool descriptions. Output ONLY the rewritten query, nothing else."
                    )
                },
                {
                    "role": "user",
                    "content": f"Tools:\n{tools_text}\n\nUser query: {query}\n\nRewritten query:"
                }
            ],
            max_tokens=60,
            temperature=0.0
        )
        usage = resp.usage
        logger.info(f"[GROQ] expand_query | prompt_tokens={usage.prompt_tokens} completion_tokens={usage.completion_tokens}")
        rewritten = resp.choices[0].message.content.strip()
        return rewritten if rewritten else query
    except Exception as e:
        logger.warning(f"[EXPAND_QUERY] failed: {e}")
        return query