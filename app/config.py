from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_file=".env")

    # Mongo
    MONGO_URI: str
    DB_NAME: str

    # Azure LLM
    AZURE_OPENAI_LLM_KEY: str
    AZURE_LLM_API_VERSION: str
    AZURE_LLM_ENDPOINT: str
    AZURE_LLM_DEPLOYMENT_41_MINI: str
    AZURE_OPENAI_EMB_KEY: str
    AZURE_OPENAI_EMB_ENDPOINT: str
    AZURE_OPENAI_EMB_API_VERSION: str
    AZURE_OPENAI_EMB_DEPLOYMENT: str

    # Notion
    notion_api_key: str = ""
    notion_database_id: str = ""
    notion_ticket_db_id: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"


settings = Settings()

MONGO_URI = settings.MONGO_URI
DB_NAME = settings.DB_NAME