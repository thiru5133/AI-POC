from alembic import context

from app import db

# Online only: migrations always run against the engine configured by the HB_DB_* settings (or HB_DATABASE_URL).
with db.get_engine().connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
