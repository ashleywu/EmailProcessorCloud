from __future__ import annotations

from app.gmail.client import GmailClient
from app.gmail.labeler import (
    ERROR_LABEL,
    INBOX_LABEL,
    PROCESSED_LABEL,
    GmailLabeler,
    category_label_name,
)
from app.models.outputs import RouteCategory
from tests.fakes import FakeGmailService, make_message


def _client_with(service: FakeGmailService) -> GmailClient:
    return GmailClient(service_factory=lambda: service)


def test_category_label_name_uses_prefix() -> None:
    assert category_label_name(RouteCategory.TECHNOLOGY) == "AI_DIGEST/TECHNOLOGY"
    assert category_label_name("RADAR") == "AI_DIGEST/RADAR"


def test_ensure_labels_creates_missing_only_once() -> None:
    service = FakeGmailService(labels={"Existing": "Label_existing"})
    labeler = GmailLabeler(_client_with(service))

    mapping = labeler.ensure_labels(["Existing", PROCESSED_LABEL, ERROR_LABEL])
    assert set(mapping.keys()) == {"Existing", PROCESSED_LABEL, ERROR_LABEL}
    assert mapping["Existing"] == "Label_existing"

    create_calls = service.call_kwargs("labels.create")
    created_names = sorted(c["body"]["name"] for c in create_calls)
    assert created_names == sorted([PROCESSED_LABEL, ERROR_LABEL])

    mapping_again = labeler.ensure_labels([PROCESSED_LABEL])
    assert mapping_again[PROCESSED_LABEL] == mapping[PROCESSED_LABEL]
    assert len(service.call_kwargs("labels.create")) == 2


def test_mark_processed_does_not_archive() -> None:
    service = FakeGmailService(
        messages={"m1": make_message(msg_id="m1", label_ids=["INBOX"])},
    )
    labeler = GmailLabeler(_client_with(service))

    labeler.mark_processed("m1")

    modify_calls = service.call_kwargs("messages.modify")
    assert len(modify_calls) == 1
    body = modify_calls[0]["body"]
    assert "removeLabelIds" not in body
    assert INBOX_LABEL in service.message_labels["m1"]
    processed_id = service.labels[PROCESSED_LABEL]
    assert processed_id in service.message_labels["m1"]


def test_mark_error_does_not_archive() -> None:
    service = FakeGmailService(
        messages={"m1": make_message(msg_id="m1", label_ids=["INBOX"])},
    )
    labeler = GmailLabeler(_client_with(service))

    labeler.mark_error("m1")

    assert INBOX_LABEL in service.message_labels["m1"]
    error_id = service.labels[ERROR_LABEL]
    assert error_id in service.message_labels["m1"]


def test_archive_removes_inbox_only_when_called() -> None:
    service = FakeGmailService(
        messages={"m1": make_message(msg_id="m1", label_ids=["INBOX"])},
    )
    labeler = GmailLabeler(_client_with(service))

    labeler.archive("m1")

    assert INBOX_LABEL not in service.message_labels["m1"]
    modify_calls = service.call_kwargs("messages.modify")
    assert len(modify_calls) == 1
    assert modify_calls[0]["body"]["removeLabelIds"] == [INBOX_LABEL]


def test_add_category_creates_and_applies_label() -> None:
    service = FakeGmailService(
        messages={"m1": make_message(msg_id="m1", label_ids=["INBOX"])},
    )
    labeler = GmailLabeler(_client_with(service))

    labeler.add_category("m1", RouteCategory.TECHNOLOGY)

    label_id = service.labels["AI_DIGEST/TECHNOLOGY"]
    assert label_id in service.message_labels["m1"]
    assert INBOX_LABEL in service.message_labels["m1"]


def test_add_labels_with_explicit_remove_supports_archive_combo() -> None:
    service = FakeGmailService(
        messages={"m1": make_message(msg_id="m1", label_ids=["INBOX"])},
    )
    labeler = GmailLabeler(_client_with(service))

    labeler.add_labels("m1", [PROCESSED_LABEL], remove=[INBOX_LABEL])

    processed_id = service.labels[PROCESSED_LABEL]
    assert processed_id in service.message_labels["m1"]
    assert INBOX_LABEL not in service.message_labels["m1"]
