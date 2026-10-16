import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse
from keel.server import api_events
from keel.principal import Principal
from keel import repo


def _mock_request(query_params: dict):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/events",
        "query_string": "&".join(f"{k}={v}" for k, v in query_params.items()).encode(),
        "headers": [],
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_api_events_defaults_and_calls_repo():
    req = _mock_request({})
    principal = Principal(project_id="00000000-0000-0000-0000-000000000001", person_id="p1", session_id="s1")

    mock_row = {
        "id": 10,
        "actor": "alice",
        "action": "test.action",
        "payload_json": json.dumps({"key": "val"}),
        "created_at": datetime.now(timezone.utc),
    }

    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    with patch("keel.server.current_principal", return_value=principal), \
         patch("keel.server.db.get_pool", return_value=mock_pool), \
         patch("keel.repo.list_events", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [mock_row]

        resp = await api_events(req)
        assert resp.status_code == 200
        data = json.loads(resp.body)

        mock_list.assert_awaited_once_with(mock_conn, principal.project_id, 100, before_id=None)
        assert len(data["events"]) == 1
        assert data["events"][0]["id"] == 10
        # Since rows returned (1) is less than limit (100), next_cursor is None
        assert data["next_cursor"] is None


@pytest.mark.asyncio
async def test_api_events_before_id_and_cursor():
    principal = Principal(project_id="00000000-0000-0000-0000-000000000001", person_id="p1", session_id="s1")
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    mock_rows = [
        {"id": 42, "actor": "a", "action": "x", "payload_json": "{}", "created_at": datetime.now(timezone.utc)},
        {"id": 41, "actor": "a", "action": "x", "payload_json": "{}", "created_at": datetime.now(timezone.utc)},
    ]

    # Test before_id param and limit clamping
    req = _mock_request({"limit": "2", "before_id": "50"})
    with patch("keel.server.current_principal", return_value=principal), \
         patch("keel.server.db.get_pool", return_value=mock_pool), \
         patch("keel.repo.list_events", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = mock_rows

        resp = await api_events(req)
        assert resp.status_code == 200
        data = json.loads(resp.body)

        mock_list.assert_awaited_once_with(mock_conn, principal.project_id, 2, before_id=50)
        assert data["next_cursor"] == 41

    # Test cursor alias
    req2 = _mock_request({"limit": "2", "cursor": "50"})
    with patch("keel.server.current_principal", return_value=principal), \
         patch("keel.server.db.get_pool", return_value=mock_pool), \
         patch("keel.repo.list_events", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = mock_rows

        resp = await api_events(req2)
        assert resp.status_code == 200
        mock_list.assert_awaited_once_with(mock_conn, principal.project_id, 2, before_id=50)


@pytest.mark.asyncio
async def test_api_events_invalid_cursor_returns_400():
    principal = Principal(project_id="00000000-0000-0000-0000-000000000001", person_id="p1", session_id="s1")

    for bad_cursor in ["abc", "-5", "0"]:
        req = _mock_request({"before_id": bad_cursor})
        with patch("keel.server.current_principal", return_value=principal):
            resp = await api_events(req)
            assert resp.status_code == 400
            data = json.loads(resp.body)
            assert "invalid cursor" in data["error"]


@pytest.mark.asyncio
async def test_repo_list_events_sql_generation():
    mock_conn = AsyncMock()

    # Without before_id
    await repo.list_events(mock_conn, "pid-1", 10)
    mock_conn.fetch.assert_awaited_with(
        "SELECT * FROM event WHERE project_id=$1 ORDER BY id DESC LIMIT $2",
        "pid-1", 10
    )

    # With before_id
    mock_conn.reset_mock()
    await repo.list_events(mock_conn, "pid-1", 10, before_id=99)
    mock_conn.fetch.assert_awaited_with(
        "SELECT * FROM event WHERE project_id=$1 AND id < $2 ORDER BY id DESC LIMIT $3",
        "pid-1", 99, 10
    )
