---
name: add-endpoint
description: Add a new endpoint to the FastAPI backend. Use when asked for a new route, resource or API operation.
---

# Add an endpoint

1. Define Pydantic models for the request body and the response. Name them after the domain (`Recipe`, `RecipeCreate`), not the route.
2. Add the route with `response_model`, `tags` and an explicit `status_code`. Return model instances, not dicts.
3. If the route touches user data, take `user: CurrentUser` and filter every query by `owner_id == user.id`; set `owner_id=user.id` on anything it creates. Someone else's row is a 404.
4. Raise `HTTPException` with a clear status for expected failures (404 for unknown ids, 422 is automatic for validation).
5. Add tests in `tests/` using the fixtures in `tests/conftest.py` (`client` is logged in, `anon` is not): the success case, at least one failure case, a 401 without a token, a 404 for another user's data, and an assertion that the path appears in `/openapi.json`.
6. Run `.venv/bin/pytest`, `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`.
7. The OpenAPI spec changed, so mention it in your summary: the web app's generated client will need regenerating.
