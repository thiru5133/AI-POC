from sqlalchemy import func, select, true

from app.models import McpServer
from app.repositories.base import TenantScopedRepository


class McpServerRepository(TenantScopedRepository[McpServer]):
    model = McpServer

    def list_all(self) -> list[McpServer]:
        return list(self.session.scalars(self._select().order_by(McpServer.created_at)))

    def list_enabled(self) -> list[McpServer]:
        return list(self.session.scalars(self._select().where(McpServer.enabled == true()).order_by(McpServer.created_at)))

    def get_by_name(self, name: str) -> McpServer | None:
        return self.session.scalars(self._select().where(func.lower(McpServer.name) == name.lower())).first()

    def count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(McpServer).where(McpServer.tenant_id == self.tenant_id)) or 0

    def delete(self, server: McpServer) -> None:
        self.session.delete(server)
        self.session.flush()
