from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from app import routes_admin, routes_auth, routes_public
from app.security import require_api_key
from app.service import DomainError

app = FastAPI(title="HolidayBooking API")


@app.exception_handler(DomainError)
async def domain_error(_: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


@app.get("/api/health")
def health():
    return {"status": "ok"}  # open: the container healthcheck needs it


# Everything else needs the API key; admin routes additionally need a staff login (see routes_admin).
api = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])
api.include_router(routes_public.router)
api.include_router(routes_auth.router)
api.include_router(routes_admin.router)
app.include_router(api)
