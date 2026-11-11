import re
import unicodedata

MAX_LENGTH = 180  # Leaves room in recipe.slug (200) for a "-N" suffix.
FALLBACK = "recipe"

# Letters NFKD can't reduce to ASCII: Russian (BGN/PCGN-style, simplified) and Polish ł.
_TRANSLIT = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
        "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
        "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
        "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
        "я": "ya", "ł": "l",
    }
)  # fmt: skip


def slugify(title: str) -> str:
    """URL-safe ASCII slug from a title in any of our locales."""
    text = title.lower().translate(_TRANSLIT)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return slug[:MAX_LENGTH].rstrip("-") or FALLBACK
