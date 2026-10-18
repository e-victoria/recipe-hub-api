# Recipe Hub API

FastAPI backend for Recipe Hub. The web app lives in `../recipe-hub`.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn app.main:app --reload --port 8000
```

- API docs: http://localhost:8000/docs
- OpenAPI spec: http://localhost:8000/openapi.json
- Tests: `.venv/bin/pytest`
- Lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
