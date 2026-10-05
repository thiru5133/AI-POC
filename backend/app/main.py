import logging
import uuid

from fastapi import FastAPI, Request

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, request_id_var

configure_logging(get_settings().log_level)
log = logging.getLogger(__name__)

app = FastAPI(title="AI Universal Receptionist")
register_error_handlers(app)
app.include_router(router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    return response
