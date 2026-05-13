from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://weihai:weihai_dev@localhost:5432/weihai_lab"
    openai_api_key: str = ""
    claude_api_key: str = ""
    gamma_api_key: str = ""
    wechat_app_id: str = "local-dev"
    wechat_app_secret: str = "local-dev"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "weihai-assets"


@lru_cache
def get_settings() -> Settings:
    return Settings()
