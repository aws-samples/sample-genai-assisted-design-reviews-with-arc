import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


class AppConfig(BaseModel):
    """Application-specific configuration."""

    # Processing Configuration
    data_dir: Path = Field(default_factory=lambda: Path(os.getenv('DATA_DIR', 'data')))
    cache_dir: Path = Field(default_factory=lambda: Path(os.getenv('CACHE_DIR', 'data/cache')))
    output_dir: Path = Field(default_factory=lambda: Path(os.getenv('OUTPUT_DIR', 'artifacts')))

    # Document Processing
    max_document_size_mb: float = Field(default_factory=lambda: float(os.getenv('MAX_DOCUMENT_SIZE_MB', '4.5')))

    # Logging Configuration
    log_level: str = Field(default_factory=lambda: os.getenv('LOG_LEVEL', 'INFO'))
    log_format: str = Field(
        default_factory=lambda: os.getenv('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

    # AWS region
    region: str = Field(default_factory=lambda: os.getenv('AWS_DEFAULT_REGION', 'us-west-2'))

    # FMs
    fm_id: str = Field(default_factory=lambda: os.getenv('MODEL', 'global.anthropic.claude-sonnet-4-5-20250929-v1:0'))

    @field_validator('cache_dir', 'output_dir', mode='after')
    @classmethod
    def create_directory(cls, v: Path) -> Path:
        try:
            v.mkdir(parents=True, exist_ok=True)
            return v
        except Exception as e:
            raise ValueError(f"Cannot create directory {v}: {e}")

    class Config:
        validate_assignment = True
        validate_default = True


# Use user-provided environment
load_dotenv()
config = AppConfig()
