from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.auth.security import utcnow
from app.models import RefreshToken, User


class UserRepository:
    """Deliberately not tenant-scoped: login and superadmin review happen before/above any tenant."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, user_id: str) -> User | None:
        return self.session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self.session.scalars(select(User).where(User.email == email)).first()

    def get_by_name(self, name: str) -> User | None:
        return self.session.scalars(select(User).where(func.lower(User.name) == name.lower())).first()

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user

    def _conditions(self, status: str | None, role: str | None, q: str | None) -> list:
        conds = []
        if status:
            conds.append(User.status == status)
        if role:
            conds.append(User.role == role)
        if q and q.strip():
            esc = "\\"
            needle = q.strip().lower().replace(esc, esc * 2).replace("%", esc + "%").replace("_", esc + "_")
            pattern = f"%{needle}%"
            conds.append(
                or_(func.lower(User.name).like(pattern, escape=esc), func.lower(User.email).like(pattern, escape=esc))
            )
        return conds

    def search(
        self, status: str | None, role: str | None, q: str | None, limit: int, offset: int
    ) -> tuple[list[User], int]:
        conds = self._conditions(status, role, q)
        total = self.session.scalar(select(func.count()).select_from(User).where(*conds)) or 0
        rows = self.session.scalars(
            select(User).where(*conds).order_by(User.created_at.desc(), User.id).limit(limit).offset(offset)
        )
        return list(rows), total

    def status_counts(self, role: str | None, q: str | None) -> dict[str, int]:
        """Counts per status for the current role/search (ignores the status filter, so tabs show all totals)."""
        conds = self._conditions(None, role, q)
        rows = self.session.execute(select(User.status, func.count()).where(*conds).group_by(User.status))
        return {status: count for status, count in rows}

    def list_admins(self, status: str | None = None) -> list[User]:
        stmt = select(User).where(User.role == "admin").order_by(User.created_at)
        if status:
            stmt = stmt.where(User.status == status)
        return list(self.session.scalars(stmt))

    # ---- refresh tokens ----
    def add_refresh_token(self, token: RefreshToken) -> None:
        self.session.add(token)
        self.session.flush()

    def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        return self.session.scalars(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).first()

    def revoke_all_tokens(self, user_id: str) -> None:
        self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
