from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Mongo
    MONGO_URI: str
    DB_NAME: str

    # Azure LLM
    AZURE_OPENAI_LLM_KEY: str
    AZURE_LLM_API_VERSION: str
    AZURE_LLM_ENDPOINT: str
    AZURE_LLM_DEPLOYMENT_41_MINI: str
    # Notion
    notion_api_key: str = ""
    notion_database_id: str = ""
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    class Config:
        env_file = ".env"

settings = Settings()

MONGO_URI = settings.MONGO_URI
DB_NAME = settings.DB_NAME
