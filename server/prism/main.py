from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from prism.config import get_settings
from prism.db import engine
from prism.uploads import UploadGuard, reconcile_uploads
from prism.uploads import router as uploads_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    reconcile_uploads()
    yield
    engine.dispose()


app = FastAPI(title="Prism API", version="0.1.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.add_middleware(UploadGuard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Prism-Request"],
)
app.include_router(uploads_router)


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    api: Literal["ok"] = "ok"
    database: Literal["ok", "unavailable"]


@app.get("/health", response_model=Health)
def health(response: Response) -> Health:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = 503
        return Health(status="degraded", database="unavailable")
    return Health(status="ok", database="ok")
