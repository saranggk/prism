from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PRISM_", env_file=PROJECT_ROOT / ".env", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://prism:prism@127.0.0.1:5432/prism"
    frontend_origin: str = "http://127.0.0.1:3000"
    data_dir: Path = PROJECT_ROOT / "data"
    search_similarity_cutoff: float = 0.3  # Provisional until development labels exist.
    visual_similarity_cutoff: float = 0.285  # Calibrated on tutorial development questions.
    silent_visual_similarity_cutoff: float = (
        0.25  # Calibrated on silent-demo development questions.
    )
    image_similarity_cutoff: float = 0.65  # Provisional; calibrate on image-query development data.

    @property
    def storage_path(self) -> Path:
        return self.data_dir if self.data_dir.is_absolute() else PROJECT_ROOT / self.data_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
