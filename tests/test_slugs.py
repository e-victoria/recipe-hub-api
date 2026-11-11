import pytest

from app.slugs import slugify


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Apple Pie", "apple-pie"),
        ("  Crème brûlée!  ", "creme-brulee"),
        ("Żurek z białą kiełbasą", "zurek-z-biala-kielbasa"),
        ("Борщ с пампушками", "borshch-s-pampushkami"),
        ("Щи-да-каша", "shchi-da-kasha"),
        ("50/50 salad", "50-50-salad"),
        ("!!!", "recipe"),
        ("漢字", "recipe"),
    ],
)
def test_slugify(title: str, expected: str) -> None:
    assert slugify(title) == expected


def test_slugify_limits_length_without_trailing_dash() -> None:
    slug = slugify("word " * 100)
    assert len(slug) <= 180
    assert not slug.endswith("-")
