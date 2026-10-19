# Recipe Hub API

FastAPI backend for Recipe Hub. The web app lives in `../recipe-hub`.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
docker compose up -d
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8000 --env-file .env
```

`docker compose` starts Postgres and RustFS (an S3-compatible store for images, console at http://localhost:9001, login `recipe_hub` / `recipe_hub_secret`). In production, set `DATABASE_URL` and `S3_BUCKET`, leave `S3_ENDPOINT_URL` unset to use AWS S3, and give the service an IAM role instead of access keys.

- API docs: http://localhost:8000/docs
- OpenAPI spec: http://localhost:8000/openapi.json
- Tests: `.venv/bin/pytest`
- Lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
