import asyncio
import logging
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import get_settings
from app.database import Base
from app.routers.notifications import router
from app.services.seeds import seed_templates
from app.services.event_consumer import run_consumer
from tms_shared.nats_client import get_nats_client, init_jetstream_streams

logger = logging.getLogger(__name__)

_consumer_task: asyncio.Task | None = None
_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _consumer_task, _http_client
    settings = get_settings()

    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await seed_templates(session)

    _http_client = httpx.AsyncClient()

    try:
        nc = await get_nats_client(settings.NATS_URL)
        js = nc.jetstream()
        await init_jetstream_streams(js)
        _consumer_task = asyncio.create_task(run_consumer(js, session_factory, _http_client))
        logger.info("Notification service NATS consumer started")
    except Exception as exc:
        logger.warning("NATS unavailable at startup: %s", exc)

    yield

    if _consumer_task:
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
    if _http_client:
        await _http_client.aclose()
    await engine.dispose()


app = FastAPI(title="TMS Notification Service", lifespan=lifespan)
Instrumentator().instrument(app).expose(app)
app.include_router(router)
