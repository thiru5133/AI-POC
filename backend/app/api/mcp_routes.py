from fastapi import APIRouter, Depends, Response

from app.api import deps
from app.api.schemas import (
    McpHeaderIn,
    McpHeaderOut,
    McpServerCreate,
    McpServerOut,
    McpServerUpdate,
    McpTestOut,
    McpToolOut,
)
from app.mcp.headers import HeaderInput, to_public
from app.mcp.service import McpConfigService, McpSettings
from app.models import McpServer, User

router = APIRouter(prefix="/api/org/mcp-servers", tags=["mcp"])


def _out(server: McpServer) -> McpServerOut:
    return McpServerOut(
        id=server.id,
        name=server.name,
        url=server.url,
        enabled=server.enabled,
        headers=[McpHeaderOut(**h) for h in to_public(server.headers)],  # secret values are never sent back
        transport=server.transport,
        timeout_seconds=server.timeout_seconds,
        created_at=server.created_at,
    )


def _headers(items: list[McpHeaderIn] | None) -> list[HeaderInput] | None:
    return None if items is None else [HeaderInput(h.name, h.value, h.secret) for h in items]


def _tenant(user: User) -> str:
    return deps.require_tenant(user)


@router.get("", response_model=list[McpServerOut])
async def list_servers(
    user: User = Depends(deps.require_admin), service: McpConfigService = Depends(deps.get_mcp_config)
):
    return [_out(s) for s in await service.list(_tenant(user))]


@router.post("", response_model=McpServerOut, status_code=201)
async def create_server(
    body: McpServerCreate,
    user: User = Depends(deps.require_admin),
    service: McpConfigService = Depends(deps.get_mcp_config),
):
    data = McpSettings(
        name=body.name,
        url=body.url,
        headers=_headers(body.headers),
        transport=body.transport,
        timeout_seconds=body.timeout_seconds,
    )
    return _out(await service.create(_tenant(user), data))


@router.patch("/{server_id}", response_model=McpServerOut)
async def update_server(
    server_id: str,
    body: McpServerUpdate,
    user: User = Depends(deps.require_admin),
    service: McpConfigService = Depends(deps.get_mcp_config),
):
    data = McpSettings(
        name=body.name,
        url=body.url,
        headers=_headers(body.headers),
        transport=body.transport,
        timeout_seconds=body.timeout_seconds,
        enabled=body.enabled,
    )
    return _out(await service.update(_tenant(user), server_id, data))


@router.delete("/{server_id}", status_code=204)
async def delete_server(
    server_id: str,
    user: User = Depends(deps.require_admin),
    service: McpConfigService = Depends(deps.get_mcp_config),
):
    await service.delete(_tenant(user), server_id)
    return Response(status_code=204)


@router.post("/{server_id}/test", response_model=McpTestOut)
async def test_server(
    server_id: str,
    user: User = Depends(deps.require_admin),
    service: McpConfigService = Depends(deps.get_mcp_config),
):
    result = await service.test(_tenant(user), server_id)
    return McpTestOut(
        ok=result.ok,
        error=result.error,
        tools=[McpToolOut(name=t.name, description=t.description) for t in result.tools],
    )
