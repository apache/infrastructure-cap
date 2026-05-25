"""Resolution-time tally rules. See SPEC §8.3.1.

The functions here are pure: they accept the question's row and a list of
response rows (typically already ordered by ``created_at`` ascending) and
return an outcome plus a tally summary that is suitable for both the audit
log's ``details_json`` and the resolved-question's ``permalink`` payload.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from cap_backend.dao import latest_response_per_voter

Outcome = Literal["approved", "vetoed", "insufficient_votes"]


def _vote_payload(row: sqlite3.Row) -> dict[str, Any]:
    return json.loads(row["response_json"])


def compute_outcome(
    question_row: sqlite3.Row,
    response_rows: list[sqlite3.Row],
) -> tuple[Outcome, dict[str, Any]]:
    approval = question_row["approval_type"]
    latest = latest_response_per_voter(response_rows)

    binding_voters = sorted({v for v, r in latest.items() if r["is_binding"]})
    all_voters = sorted(latest.keys())

    if approval == "unanimous_approval":
        return _tally_unanimous(latest, binding_voters, all_voters)
    if approval == "majority_approval":
        return _tally_majority(latest, binding_voters, all_voters)
    if approval == "lazy_consensus":
        return _tally_lazy(latest, binding_voters, all_voters)
    raise ValueError(f"Unknown approval_type: {approval!r}")


def _tally_unanimous(
    latest: dict[str, sqlite3.Row],
    binding_voters: list[str],
    all_voters: list[str],
) -> tuple[Outcome, dict[str, Any]]:
    """Approved iff no veto is in force in any voter's latest response."""
    active_vetoes = [
        {
            "voter": voter,
            "comment": row["comment"],
            "response_id": row["response_id"],
        }
        for voter, row in latest.items()
        if row["is_veto"]
    ]
    tally: dict[str, Any] = {
        "approval_type": "unanimous_approval",
        "binding_voters": binding_voters,
        "all_voters": all_voters,
        "vetoes": active_vetoes,
    }
    if active_vetoes:
        return "vetoed", tally
    return "approved", tally


def _tally_majority(
    latest: dict[str, sqlite3.Row],
    binding_voters: list[str],
    all_voters: list[str],
) -> tuple[Outcome, dict[str, Any]]:
    """Majority of binding +1 votes carries the question.

    Concretely: among the latest response of each binding voter, count
    ``value`` occurrences. The question is approved when there is at least
    one binding +1 and strictly more binding +1s than binding -1s; otherwise
    the outcome is ``insufficient_votes``.
    """
    counts = {"+1": 0, "+0": 0, "-0": 0, "-1": 0}
    binding_counts = {"+1": 0, "+0": 0, "-0": 0, "-1": 0}
    for row in latest.values():
        if row["response_kind"] != "vote":
            continue
        value = _vote_payload(row).get("value")
        if value in counts:
            counts[value] += 1
            if row["is_binding"]:
                binding_counts[value] += 1

    tally: dict[str, Any] = {
        "approval_type": "majority_approval",
        "binding_voters": binding_voters,
        "all_voters": all_voters,
        "counts": counts,
        "binding_counts": binding_counts,
    }
    if binding_counts["+1"] > 0 and binding_counts["+1"] > binding_counts["-1"]:
        return "approved", tally
    return "insufficient_votes", tally


def _tally_lazy(
    latest: dict[str, sqlite3.Row],
    binding_voters: list[str],
    all_voters: list[str],
) -> tuple[Outcome, dict[str, Any]]:
    """Silence is assent; any objection blocks approval."""
    objections: list[dict[str, Any]] = []
    for voter, row in latest.items():
        if row["response_kind"] == "lazy_consensus":
            payload = _vote_payload(row)
            if payload.get("objection") is True:
                objections.append(
                    {
                        "voter": voter,
                        "comment": row["comment"],
                        "response_id": row["response_id"],
                    }
                )
        elif row["response_kind"] == "vote":
            payload = _vote_payload(row)
            if payload.get("value") == "-1":
                objections.append(
                    {
                        "voter": voter,
                        "comment": row["comment"],
                        "response_id": row["response_id"],
                    }
                )

    tally: dict[str, Any] = {
        "approval_type": "lazy_consensus",
        "binding_voters": binding_voters,
        "all_voters": all_voters,
        "objections": objections,
    }
    if objections:
        return "insufficient_votes", tally
    return "approved", tally
