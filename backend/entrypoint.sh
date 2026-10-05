#!/bin/sh
set -e
python -m app.database.init_db
alembic upgrade head
python -m app.database.seed
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
