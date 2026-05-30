"""Email notifications for question lifecycle events.

Every state-changing action on a question (create / edit / resolve / remove /
respond) sends a notification to the relevant project mailing list. The
recipient list is determined entirely by the question's ``project_id`` and
``is_private`` flag, so neither route handlers nor callers need to know
anything about list naming.

The sender is constant across every event so subscribers can filter on it:

    From: ASF Contingent Approval Platform <root-asfcap@apache.org>

The dispatch is delegated to ``asfpy.messaging.mail``. We import it lazily
inside ``send()`` so the module remains importable in test environments that
do not have a configured MSA, and so tests can monkeypatch the dispatch
function without touching SMTP.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

import asfquart
from quart import request
from cap_backend.schemas.questions import Question

if TYPE_CHECKING:
    from cap_backend.auth import AuthenticatedUser

LOGGER = logging.getLogger(__name__)

SENDER = "ASF Contingent Approval Platform <root-asfcap@apache.org>"

NotificationEvent = Literal[
    "created",
    "edited",
    "resolved",
    "closed",
    "response",
]


def recipient_for(question: Question | Any, *, debug_recipient: str | None = None) -> str:
    """Return the mailing-list address for ``question``.

    If ``debug_recipient`` is a non-empty string, every notification is
    redirected there. Otherwise private questions go to
    ``private@{project}.apache.org`` and everything else goes to
    ``dev@{project}.apache.org``. The project component is taken verbatim
    from ``question.project_id``.
    """
    if debug_recipient:
        return debug_recipient
    project = question.project_id
    if getattr(question, "is_private", False):
        return f"private@{project}.apache.org"
    return f"dev@{project}.apache.org"


def _subject_for(event: NotificationEvent, question: Question | Any) -> str:
    qid = question.question_id
    title = getattr(question, "title", "")
    prefixes = {
        "created": "[CAP] Vote",
        "edited": "[CAP] Updated",
        "resolved": "[CAP] Resolved",
        "closed": "[CAP] Withdrawn",
        "response": "[CAP] Re",
    }
    return f"{prefixes[event]} #{qid}: {title}"


def _thread_key_for(question: Question | Any) -> str:
    return f"cap-question-{question.question_id}"


def _send_mail(**kwargs: Any) -> None:
    """Indirection so tests can monkeypatch the dispatch point.

    Importing ``asfpy.messaging`` lazily keeps the dependency optional at
    import time; on machines without an MSA configured the call will raise
    at send time, which the caller logs and swallows.
    """
    from asfpy import messaging  # noqa: PLC0415

    messaging.mail(**kwargs)


def _format_actor(actor: AuthenticatedUser | Any) -> str:
    """Render an actor line that surfaces both the UID and the fullname.

    Falls back gracefully when ``fullname`` is missing or empty: those
    sessions just show the UID. Subscribers parsing the message body can
    rely on the ``Actor:`` line always starting with the ASF UID.
    """
    uid = getattr(actor, "uid", str(actor))
    fullname = getattr(actor, "fullname", None)
    if fullname:
        return f"{uid} ({fullname})"
    return uid


def _host_url() -> str:
    """Return ``request.host_url`` when inside a request, else an empty string.

    notify.send is always called from a request handler in production, but
    unit tests reach in directly. Falling back to "" keeps the module
    usable outside a request context without crashing the caller.
    """
    try:
        return request.host_url
    except RuntimeError:
        return ""


def _footer(question: Question | Any, *, host_url: str) -> str:
    """Return the standard CAP notification footer.

    Explains why the recipient is on the distribution, who is entitled to
    respond through CAP, and where to read more about the service. The
    leading ``-- \\n`` is the conventional email signature delimiter, so
    most mail clients render the footer as a sig block visually distinct
    from the per-event body.
    """
    project = getattr(question, "project_id", "")
    return (
        "-- \n"
        f"You are receiving this notification because the Apache {project} "
        "project uses the ASF Contingent Approval Platform (CAP), an "
        "official Apache Software Foundation service for filing and "
        "recording the outcome of contingent approval votes.\n"
        "\n"
        "How to respond:\n"
        "  * Committers and committee members of the project may cast "
        "votes on this question through CAP using the link above.\n"
        "  * Only committee (PMC/PPMC) members cast binding votes; all "
        "other votes are recorded but non-binding.\n"
        "  * Anyone may view public CAP questions "
        "through the link above.\n"
        "\n"
        "Every CAP action is written to an append-only audit log inside "
        "the same database transaction as the action itself, so every "
        "recorded decision carries a fully auditable provenance trail.\n"
        "\n"
        f"To learn more about CAP, visit: {host_url}#/about\n"
    )


def send(
    event: NotificationEvent,
    question: Question | Any,
    *,
    actor: AuthenticatedUser | Any,
    body: str,
    debug_recipient: str | None = None,
) -> bool:
    """Send a single notification email. Returns True on apparent success.

    ``actor`` is the ``AuthenticatedUser`` from the session that triggered
    the action; the message body surfaces both the ASF UID and the
    human-readable ``fullname`` so list subscribers can see who acted
    without cross-referencing whimsy. The function never raises: a
    delivery failure is logged at WARNING and swallowed. The audit log
    is the durable record; email is a courtesy notification and must not
    roll back a successful state change.
    """
    recipient = recipient_for(question, debug_recipient=debug_recipient)
    subject = _subject_for(event, question)
    thread_key = _thread_key_for(question)
    is_thread_start = event == "created"

    host_url = _host_url()
    message = (
        f"Author: {_format_actor(actor)}\n"
        f"CAP link: {host_url}#/question/{question.question_id}\n"
        f"Project: {question.project_id}\n"
        f"\n\n"
        f"{body.rstrip()}\n\n"
        f"{_footer(question, host_url=host_url)}"
    )

    try:
        _send_mail(
            sender=SENDER,
            recipient=recipient,
            subject=subject,
            message=message,
            thread_start=is_thread_start,
            thread_key=thread_key,
        )
    except Exception as exc:  # noqa: BLE001 - we never want to crash a request
        LOGGER.warning(
            "Failed to send CAP notification for question %s (%s): %s",
            getattr(question, "question_id", "?"),
            event,
            exc,
        )
        print(subject)
        print(message)
        return False
    return True
