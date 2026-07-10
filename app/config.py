from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # MongoDB
    DATABASE_URL: str

    # Groq
    GROQ_API_KEY: str = "test-key-for-ci"
    LLM_MODEL: str = "llama-3.3-70b-versatile" 
    
    # Session
    SECRET_KEY: str = "dev-secret-key"

    # App
    DEBUG: bool = False
    NUM_WORKERS: int = 4

settings = Settings()