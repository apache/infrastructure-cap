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
from typing import Any, Literal

from cap_backend.schemas.questions import Question

LOGGER = logging.getLogger(__name__)

SENDER = "ASF Contingent Approval Platform <root-asfcap@apache.org>"

NotificationEvent = Literal[
    "created",
    "edited",
    "resolved",
    "closed",
    "response",
]

DEBUG_RECIPIENT = None  # Set to whatever you want all test emails to go to


def recipient_for(question: Question | Any) -> str:
    """Return the mailing-list address for ``question``.

    Private questions go to ``private@{project}.apache.org``; everything else
    goes to ``dev@{project}.apache.org``. The project component is taken
    verbatim from ``question.project_id``.
    """
    if DEBUG_RECIPIENT:
        return DEBUG_RECIPIENT
    project = question.project_id
    if getattr(question, "is_private", False):
        return f"private@{project}.apache.org"
    return f"dev@{project}.apache.org"


def _subject_for(event: NotificationEvent, question: Question | Any) -> str:
    qid = question.question_id
    title = getattr(question, "title", "")
    prefixes = {
        "created": "[CAP] New question",
        "edited": "[CAP] Question updated",
        "resolved": "[CAP] Question resolved",
        "closed": "[CAP] Question withdrawn",
        "response": "[CAP] New response",
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


def send(
    event: NotificationEvent,
    question: Question | Any,
    *,
    actor: str,
    body: str,
) -> bool:
    """Send a single notification email. Returns True on apparent success.

    The function never raises: a delivery failure is logged at WARNING and
    swallowed. The audit log is the durable record; email is a courtesy
    notification and must not roll back a successful state change.
    """
    recipient = recipient_for(question)
    subject = _subject_for(event, question)
    thread_key = _thread_key_for(question)
    is_thread_start = event == "created"

    message = (
        f"Actor: {actor}\n"
        f"Question id: {question.question_id}\n"
        f"Project: {question.project_id}\n"
        f"Event: {event}\n"
        f"\n"
        f"{body.rstrip()}\n"
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
        return False
    return True
