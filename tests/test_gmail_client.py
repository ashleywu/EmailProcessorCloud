from __future__ import annotations

import pytest

from app.gmail.client import GmailClient, _is_unauthorized
from tests.fakes import FakeGmailService, FakeHttpError


def test_is_unauthorized_detects_resp_status() -> None:
    assert _is_unauthorized(FakeHttpError(401)) is True
    assert _is_unauthorized(FakeHttpError(500)) is False


def test_service_uses_factory_and_caches() -> None:
    factory_calls = {"n": 0}

    def factory():
        factory_calls["n"] += 1
        return FakeGmailService()

    client = GmailClient(service_factory=factory)
    s1 = client.service
    s2 = client.service
    assert s1 is s2
    assert factory_calls["n"] == 1


def test_refresh_rebuilds_service_via_factory() -> None:
    services = [FakeGmailService(), FakeGmailService()]

    def factory():
        return services.pop(0)

    client = GmailClient(service_factory=factory)
    first = client.service
    second = client.refresh()
    assert first is not second
    assert client.service is second


def test_execute_retries_once_on_401_and_returns_value() -> None:
    services = [FakeGmailService(), FakeGmailService()]

    def factory():
        return services.pop(0)

    client = GmailClient(service_factory=factory)
    first_service = client.service
    first_service.queue_failure("labels.list", FakeHttpError(401))

    result = client.execute(lambda svc: svc.users().labels().list(userId="me"))

    assert result == {"labels": []}
    assert client.service is not first_service
    assert services == []


def test_execute_does_not_retry_on_non_401() -> None:
    service = FakeGmailService()

    client = GmailClient(service_factory=lambda: service)
    service.queue_failure("labels.list", FakeHttpError(500))

    with pytest.raises(FakeHttpError):
        client.execute(lambda svc: svc.users().labels().list(userId="me"))


def test_close_clears_cached_service() -> None:
    seen = []

    def factory():
        svc = FakeGmailService()
        seen.append(svc)
        return svc

    client = GmailClient(service_factory=factory)
    _ = client.service
    client.close()
    _ = client.service
    assert len(seen) == 2
