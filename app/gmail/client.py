from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

DEFAULT_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
)


def _is_unauthorized(exc: BaseException) -> bool:
    """Best-effort 401 detection that works for googleapiclient.errors.HttpError
    and any duck-typed test fakes carrying ``status``/``status_code``."""

    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "status", None)
    if status is None:
        return False
    try:
        return int(status) == 401
    except (TypeError, ValueError):
        return False


class GmailClient:
    """OAuth-aware Gmail API entry point.

    The client is intentionally split from the fetcher/labeler/sender so
    that tests can inject a fake service (or a fresh one on refresh) via
    ``service_factory`` without touching Google libraries or credential
    files. In production the constructor only needs the credential and
    token paths; google libraries are imported lazily so importing this
    module never requires them at install time.
    """

    SCOPES: tuple[str, ...] = DEFAULT_SCOPES

    def __init__(
        self,
        credentials_path: str | Path | None = None,
        token_path: str | Path | None = None,
        *,
        scopes: Iterable[str] | None = None,
        service_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._credentials_path = Path(credentials_path) if credentials_path else None
        self._token_path = Path(token_path) if token_path else None
        self._scopes = tuple(scopes) if scopes is not None else self.SCOPES
        self._service_factory = service_factory
        self._service: Any = None
        self._creds: Any = None

    @property
    def service(self) -> Any:
        """Return the cached Gmail service, building/loading on first access."""

        if self._service is None:
            self._service = self._build_or_inject_service()
        return self._service

    def refresh(self) -> Any:
        """Refresh the access token (or re-create an injected service) and
        return the resulting service object."""

        if self._service_factory is not None:
            self._service = self._service_factory()
            return self._service

        if self._creds is None:
            self._creds = self._load_credentials()
        else:
            self._refresh_credentials(self._creds)
            self._persist_token(self._creds)

        self._service = self._build_service(self._creds)
        return self._service

    def execute(self, build_request: Callable[[Any], Any]) -> Any:
        """Run a Gmail API call with automatic 401 refresh-and-retry.

        ``build_request`` receives the current service and returns a
        request object (one with ``.execute()``). On a 401 the client
        refreshes credentials and rebuilds the request against the new
        service before retrying exactly once.
        """

        try:
            return build_request(self.service).execute()
        except Exception as exc:  # noqa: BLE001 - we re-raise non-401s
            if not _is_unauthorized(exc):
                raise
            self.refresh()
            return build_request(self.service).execute()

    def close(self) -> None:
        """Drop cached service/credentials so they are rebuilt on next use."""

        self._service = None
        self._creds = None

    def _build_or_inject_service(self) -> Any:
        if self._service_factory is not None:
            return self._service_factory()
        self._creds = self._load_credentials()
        return self._build_service(self._creds)

    def _is_interactive_oauth_allowed(self) -> bool:
        """Browser-based OAuth is only for local dev — not cron/headless VPS."""

        import os

        if os.environ.get("GMAIL_OAUTH_INTERACTIVE", "").strip() in {"1", "true", "yes"}:
            return True
        if os.environ.get("DISPLAY"):
            return True
        return sys.stdin.isatty() and sys.stdout.isatty()

    def _load_credentials(self) -> Any:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None
        if self._token_path and self._token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(self._token_path), list(self._scopes)
            )

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            from google.auth.exceptions import RefreshError

            try:
                creds.refresh(Request())
                self._persist_token(creds)
                return creds
            except RefreshError as exc:
                if self._is_interactive_oauth_allowed():
                    if self._token_path and self._token_path.exists():
                        self._token_path.unlink(missing_ok=True)
                    creds = None
                else:
                    msg = (
                        "Gmail OAuth refresh failed on a headless host (cron/VPS). "
                        "Re-authorize on a machine with a browser, copy "
                        f"{self._token_path} to the server, or run once with "
                        "GMAIL_OAUTH_INTERACTIVE=1. "
                        f"Refresh error: {exc}"
                    )
                    raise RuntimeError(msg) from exc

        if self._credentials_path is None:
            raise RuntimeError(
                "GmailClient: no valid token and no credentials_path provided."
            )
        if not self._is_interactive_oauth_allowed():
            raise RuntimeError(
                "Gmail token missing or invalid; interactive OAuth is disabled on "
                "this headless host. Refresh secrets/token.json from a machine with a "
                "browser (see docs/deploy-vps.md)."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._credentials_path), list(self._scopes)
        )
        creds = flow.run_local_server(port=0)
        self._persist_token(creds)
        return creds

    def _refresh_credentials(self, creds: Any) -> None:
        from google.auth.transport.requests import Request

        if not getattr(creds, "refresh_token", None):
            raise RuntimeError("GmailClient: credentials have no refresh_token.")
        creds.refresh(Request())

    def _persist_token(self, creds: Any) -> None:
        if self._token_path is None:
            return
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(creds.to_json(), encoding="utf-8")

    def _build_service(self, creds: Any) -> Any:
        from googleapiclient.discovery import build

        return build("gmail", "v1", credentials=creds, cache_discovery=False)
