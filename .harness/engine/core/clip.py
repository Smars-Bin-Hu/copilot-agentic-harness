"""A text cut to a length for a person (1.7.38, C12 RC-3): between words, with an ellipsis, never inside a word. Stdlib only."""

from __future__ import annotations


def words(text: object, limit: int) -> str:
    """At most `limit` characters on one line. A longer text is cut at the last space before the limit and ends with `…`; a text with no space in reach (a path, an address) is cut at the limit."""
    one = " ".join(str(text or "").split())
    if len(one) <= limit:
        return one
    head = one[: limit - 1]
    if one[limit - 1] != " ":  # the cut falls inside a word: back to the space before it, when that leaves most of the text
        space = head.rfind(" ")
        if space >= limit // 2:
            head = head[:space]
    return head.rstrip(" ,;:(-") + "…"
