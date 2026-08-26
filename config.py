from pydantic_settings import BaseSettings, SettingsConfigDict
import os

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

class Setting(BaseSettings):
    groq_api_key: str
    embedder: str = "all-MiniLM-L6-v2"
    max_response_tokens: int = 200
    allowed_dir: str = os.path.expanduser("~")
    tool_confidence_threshold : float =0.30
    remote_tool_confidence_threshold : float=0.35
    api_port : int = 7737
    dashboard_port : int = 7738

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        extra="ignore"
    )

settings = Setting()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
