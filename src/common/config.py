from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Roadmap Item [6] SSOT Configurations (`pydantic-settings`)
    Single Source of Truth for all environmental and application settings.
    """
    # LLM Settings
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    default_model: str = "gpt-4"
    max_context_tokens: int = 4000
    
    # Auth
    trading_ui_password: str = "alpha2026"
    
    # Path/Data locations
    qlib_data_path: str = "./data"
    artifacts_dir: str = "artifacts"
    models_dir: str = "models"
    
    # Trading Limits
    max_total_leverage: float = 2.0
    max_position_weight: float = 0.15
    volatility_vix_panic_threshold: float = 35.0
    max_daily_loss_pct: float = -0.05
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

# Global instance to be imported anywhere in the app
config = Settings()
