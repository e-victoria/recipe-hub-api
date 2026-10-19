from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.db import get_engine
from app.settings import settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_engine()  # Fail at startup, not on the first request, if DATABASE_URL is missing.
    yield


app = FastAPI(title="Recipe Hub API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Health(BaseModel):
    status: str
    version: str


@app.get("/health", response_model=Health, tags=["meta"])
def health() -> Health:
    return Health(status="ok", version=app.version)
