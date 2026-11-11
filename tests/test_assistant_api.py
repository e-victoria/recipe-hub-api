from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import schemas
from app.assistant import (
    AssistantUnavailable,
    Proposal,
    ProposedChange,
    build_prompt,
    get_assistant,
    to_advice,
)
from app.main import app
from app.ratelimit import RateLimiter, get_rate_limits

URL = "/assistant/ingredients"


class FakeAssistant:
    def __init__(self) -> None:
        self.requests: list[schemas.IngredientAdviceRequest] = []
        self.proposal = Proposal(
            reply="Swap the eggs for flaxseed.",
            changes=[
                ProposedChange(
                    action="replace",
                    line=2,
                    ingredient="2 tbsp ground flaxseed",
                    reason="Binds like egg.",
                ),
                ProposedChange(action="add", line=2, ingredient="6 tbsp water", reason="For it."),
            ],
        )
        self.error: Exception | None = None

    def advise(self, body: schemas.IngredientAdviceRequest) -> Proposal:
        self.requests.append(body)
        if self.error:
            raise self.error
        return self.proposal


@pytest.fixture
def assistant(anon: TestClient) -> Iterator[FakeAssistant]:
    # Depends on `anon`, which clears all overrides on teardown.
    fake = FakeAssistant()
    app.dependency_overrides[get_assistant] = lambda: fake
    yield fake


def advice_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "locale": "en",
        "reply_locale": "pl",
        "title": "Dumplings",
        "servings": 4,
        "ingredients": ["500 g flour", "2 eggs"],
        "steps": ["Mix", "Boil"],
        "request": "Make it vegan",
    }
    body.update(overrides)
    return body


def change(action: str, line: int | None, ingredient: str | None = None) -> ProposedChange:
    return ProposedChange(action=action, line=line, ingredient=ingredient, reason="why")


def test_advice_returns_changes_with_zero_based_indexes(
    client: TestClient, assistant: FakeAssistant
) -> None:
    response = client.post(URL, json=advice_body())

    assert response.status_code == 200
    assert response.json() == {
        "reply": "Swap the eggs for flaxseed.",
        "changes": [
            {
                "action": "replace",
                "index": 1,
                "ingredient": "2 tbsp ground flaxseed",
                "reason": "Binds like egg.",
            },
            {"action": "add", "index": 1, "ingredient": "6 tbsp water", "reason": "For it."},
        ],
    }
    assert assistant.requests[0].request == "Make it vegan"
    assert assistant.requests[0].ingredients == ["500 g flour", "2 eggs"]


def test_advice_works_on_an_empty_list(client: TestClient, assistant: FakeAssistant) -> None:
    assistant.proposal = Proposal(reply="Start with flour.", changes=[change("add", None, "flour")])

    response = client.post(URL, json=advice_body(ingredients=[], steps=[], title=None))

    assert response.status_code == 200
    assert response.json()["changes"][0]["index"] is None


@pytest.mark.parametrize(
    "body",
    [
        advice_body(request="  "),
        advice_body(request="x" * 501),
        advice_body(ingredients=["flour"] * 201),
        advice_body(ingredients=["x" * 2001]),
        advice_body(reply_locale="de"),
        advice_body(model="other"),
    ],
    ids=["blank-request", "long-request", "too-many-lines", "long-line", "locale", "extra-field"],
)
def test_advice_rejects_invalid_input(
    client: TestClient, assistant: FakeAssistant, body: dict[str, Any]
) -> None:
    assert client.post(URL, json=body).status_code == 422
    assert assistant.requests == []


def test_advice_requires_sign_in(anon: TestClient, assistant: FakeAssistant) -> None:
    assert anon.post(URL, json=advice_body()).status_code == 401
    assert assistant.requests == []


def test_advice_is_503_when_not_configured(client: TestClient) -> None:
    app.dependency_overrides[get_assistant] = lambda: None

    assert client.post(URL, json=advice_body()).status_code == 503


def test_advice_is_502_when_the_provider_fails(
    client: TestClient, assistant: FakeAssistant
) -> None:
    assistant.error = AssistantUnavailable()

    response = client.post(URL, json=advice_body())

    assert response.status_code == 502
    assert response.json() == {"detail": "assistant unavailable"}


def test_advice_is_rate_limited_per_user(
    client: TestClient, stranger: TestClient, assistant: FakeAssistant
) -> None:
    app.dependency_overrides[get_rate_limits]().assistant = RateLimiter(2, 60)

    assert client.post(URL, json=advice_body()).status_code == 200
    assert client.post(URL, json=advice_body()).status_code == 200
    assert client.post(URL, json=advice_body()).status_code == 429
    assert stranger.post(URL, json=advice_body()).status_code == 200
    assert len(assistant.requests) == 3


def test_openapi_describes_the_assistant(client: TestClient) -> None:
    route = client.get("/openapi.json").json()["paths"][URL]["post"]

    assert route["security"]
    assert route["tags"] == ["assistant"]
    assert route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/IngredientAdvice"
    )


def test_to_advice_drops_changes_that_cannot_be_applied() -> None:
    proposal = Proposal(
        reply=" Done. ",
        changes=[
            change("replace", 1, " oat milk "),
            change("remove", 1),  # Line 1 is already replaced.
            change("replace", 3, "x"),  # No such line.
            change("remove", 0),  # Lines start at 1.
            change("replace", None, "x"),  # Nothing to replace.
            change("replace", 2, "  "),  # Nothing to put there.
            change("add", None, None),
            change("remove", 2, "ignored"),
            change("add", 2, "salt"),  # Adding after an edited line is fine.
            change("add", None, "pepper"),
        ],
    )

    advice = to_advice(proposal, ingredient_count=2)

    assert advice.reply == "Done."
    assert [(c.action, c.index, c.ingredient) for c in advice.changes] == [
        ("replace", 0, "oat milk"),
        ("remove", 1, None),
        ("add", 1, "salt"),
        ("add", None, "pepper"),
    ]


def test_prompt_numbers_lines_from_one_and_names_the_languages() -> None:
    body = schemas.IngredientAdviceRequest(**advice_body(locale="ru", ingredients=["мука", "яйца"]))

    prompt = build_prompt(body)

    assert '{"line": 2, "text": "яйца"}' in prompt
    assert '"recipe_language": "Russian"' in prompt
    assert '"reply_language": "Polish"' in prompt
    assert '"request": "Make it vegan"' in prompt
