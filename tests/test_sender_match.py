from __future__ import annotations

from app.parsing.sender_match import (
    normalize_sender_allowlist,
    normalize_sender_email,
    sender_matches_map_reduce,
)


def test_normalize_display_name_format() -> None:
    assert (
        normalize_sender_email("AINews <swyx+ainews@substack.com>")
        == "swyx+ainews@substack.com"
    )


def test_allowlist_case_insensitive() -> None:
    allowed = normalize_sender_allowlist(["SWYX+ainews@substack.com"])
    assert sender_matches_map_reduce(
        "ainews <swyx+ainews@substack.com>",
        allowed,
    )


def test_multiple_senders_csv_style() -> None:
    allowed = normalize_sender_allowlist(
        ["a@x.com", "b@y.com"],
    )
    assert sender_matches_map_reduce("Team <a@x.com>", allowed)
    assert sender_matches_map_reduce("b@y.com", allowed)
    assert not sender_matches_map_reduce("c@z.com", allowed)


def test_empty_from_does_not_match() -> None:
    assert not sender_matches_map_reduce(None, ["a@x.com"])
    assert not sender_matches_map_reduce("", ["a@x.com"])
