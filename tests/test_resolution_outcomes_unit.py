"""Domain-level resolution checks; PostgreSQL transaction tests live separately."""
import uuid
from unittest.mock import AsyncMock

import pytest

from keel import repo
from keel.principal import Principal
from keel.tools.resolve_conflict import _apply_outcome, _lock_resolution_decisions, resolve_conflict


@pytest.fixture
def decisions(monkeypatch):
    owner, other, project, old, new = [uuid.uuid4() for _ in range(5)]
    rows = {old: {"id": old, "project_id": project, "owner_person_id": owner,
                  "status": "active", "scope_tags": ["api:orders"], "supersedes_id": None},
            new: {"id": new, "project_id": project, "owner_person_id": other,
                  "status": "active", "scope_tags": ["api:orders"], "supersedes_id": None}}

    async def reject(conn, decision_id):
        rows[decision_id]["status"] = "rejected"

    async def supersede(conn, decision_id):
        rows[decision_id]["status"] = "superseded"

    async def link(conn, decision_id, previous_id):
        rows[decision_id]["supersedes_id"] = previous_id

    monkeypatch.setattr(repo, "reject_decision", AsyncMock(side_effect=reject))
    monkeypatch.setattr(repo, "mark_superseded", AsyncMock(side_effect=supersede))
    monkeypatch.setattr(repo, "link_supersedes", AsyncMock(side_effect=link))
    return Principal(project, owner, "s1"), rows, old, new


@pytest.mark.parametrize("outcome", ["keep_existing", "accept_new"])
async def test_choice_leaves_only_the_selected_decision_active(decisions, outcome):
    principal, rows, old, new = decisions
    kept, retired = await _apply_outcome(None, principal, rows, old, new, outcome)
    active = [r for r in rows.values() if r["status"] == "active"]
    assert active == [kept]
    assert retired["id"] != kept["id"]
    if outcome == "accept_new":
        assert kept["id"] == new and kept["supersedes_id"] == old
        assert retired["status"] == "superseded"
    else:
        assert kept["id"] == old and retired["status"] == "rejected"


async def test_only_existing_owner_can_choose(decisions):
    principal, rows, old, new = decisions
    unauthorized = Principal(principal.project_id, rows[new]["owner_person_id"], "s2")
    with pytest.raises(PermissionError):
        await _apply_outcome(None, unauthorized, rows, old, new, "keep_existing")
    assert all(r["status"] == "active" for r in rows.values())


async def test_stale_decision_cannot_be_reactivated(decisions):
    principal, rows, old, new = decisions
    rows[new]["status"] = "rejected"
    with pytest.raises(ValueError, match="no longer active"):
        await _apply_outcome(None, principal, rows, old, new, "accept_new")
    assert rows[old]["status"] == "active"


async def test_existing_lineage_is_not_overwritten(decisions):
    principal, rows, old, new = decisions
    rows[new]["supersedes_id"] = uuid.uuid4()
    with pytest.raises(ValueError, match="different decision"):
        await _apply_outcome(None, principal, rows, old, new, "accept_new")
    assert all(r["status"] == "active" for r in rows.values())


async def test_unrecorded_action_cannot_be_accepted(decisions):
    principal, rows, old, new = decisions
    with pytest.raises(ValueError, match="recorded decision"):
        await _lock_resolution_decisions(
            None, principal, {"decision_a_id": old, "subject_type": "planned_action"}, "accept_new")


async def test_foreign_subject_rejected_before_mutations(decisions, monkeypatch):
    principal, rows, old, new = decisions
    rows[new]["project_id"] = uuid.uuid4()
    monkeypatch.setattr(repo, "get_decision", AsyncMock(side_effect=lambda conn, key: rows[key]))
    with pytest.raises(ValueError, match="project"):
        await _lock_resolution_decisions(
            None, principal, {"decision_a_id": old, "subject_type": "decision", "subject_ref": str(new)},
            "keep_existing")
    assert all(r["status"] == "active" for r in rows.values())


@pytest.mark.parametrize("kwargs", [{"outcome": "typo", "resolution": "note"}, {"resolution": " "}])
async def test_invalid_request_does_not_open_a_transaction(decisions, kwargs):
    principal, rows, old, new = decisions
    with pytest.raises(ValueError):
        await resolve_conflict(None, principal, conflict_id=str(uuid.uuid4()), **kwargs)
