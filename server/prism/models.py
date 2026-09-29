from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Video(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    duration_seconds: float
    status: Literal["queued", "processing", "ready", "failed"]
    current_step: str | None
    error: str | None
    transcript_state: Literal["present", "none"] | None = None
    created_at: datetime
    updated_at: datetime
