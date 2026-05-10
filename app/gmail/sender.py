from __future__ import annotations

import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def build_html_message(
    *,
    sender: str,
    to: str,
    subject: str,
    html: str,
    plain: str | None = None,
) -> dict[str, str]:
    """Build a Gmail-API ready ``{"raw": ...}`` payload for a multipart
    HTML message.

    The result is base64url-encoded as required by the Gmail send API.
    A plain-text alternative is included whenever supplied for clients
    that do not render HTML.
    """

    if not subject:
        raise ValueError("subject is required.")
    if not to:
        raise ValueError("to is required.")
    if not sender:
        raise ValueError("sender is required.")
    if not html:
        raise ValueError("html body is required.")

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject

    if plain:
        msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    raw_bytes = msg.as_bytes()
    encoded = base64.urlsafe_b64encode(raw_bytes).decode("ascii")
    return {"raw": encoded}


class GmailSender:
    """Send digest emails via the Gmail API.

    The sender holds the configured "From" address (typically the
    authenticated user, e.g. ``"me"`` or a verified send-as alias) and
    delegates auth/transport to the injected ``client``.
    """

    def __init__(
        self,
        client,
        *,
        sender: str,
        user_id: str = "me",
    ) -> None:
        if not sender:
            raise ValueError("GmailSender requires a non-empty sender address.")
        self._client = client
        self._sender = sender
        self._user_id = user_id

    @property
    def sender_address(self) -> str:
        return self._sender

    def send_html(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        plain: str | None = None,
    ) -> str:
        body = build_html_message(
            sender=self._sender,
            to=to,
            subject=subject,
            html=html,
            plain=plain,
        )
        response = self._client.execute(
            lambda svc: svc.users()
            .messages()
            .send(userId=self._user_id, body=body)
        )
        if "id" not in response:
            raise RuntimeError(
                f"Gmail send response missing 'id' field: {response!r}"
            )
        return str(response["id"])
