from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.main import app
from app.services.file_storage import LocalFileStorage
from app.services.persistence import MemoryRepository
from app.services.rate_limit import RateLimiter, client_ip
from tests.pdf_factory import make_pdf, make_store
from tests.test_chat import PAGES


def _request(remote: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (remote, 1234), "headers": headers})


def test_rate_limiter_blocks_after_limit_per_client():
    limiter = RateLimiter(per_hour=2, what="questions")
    limiter.check("a")
    limiter.check("a")
    with pytest.raises(HTTPException) as exc:
        limiter.check("a")
    assert exc.value.status_code == 429 and "2 questions per hour" in exc.value.detail
    limiter.check("b")  # other clients are unaffected


def test_rate_limiter_zero_means_unlimited():
    limiter = RateLimiter(per_hour=0, what="uploads")
    for _ in range(100):
        limiter.check("a")


def test_client_ip_behind_proxies_ignores_spoofed_entries():
    # Caddy appended the real client, nginx appended Caddy's address.
    req = _request("172.18.0.5", "6.6.6.6, 81.2.3.4, 172.18.0.2")
    assert client_ip(req, trusted_proxy_hops=2) == "81.2.3.4"
    assert client_ip(req, trusted_proxy_hops=0) == "172.18.0.5"
    assert client_ip(_request("10.0.0.1"), trusted_proxy_hops=2) == "10.0.0.1"


def test_purge_deletes_old_documents_files_and_chats(tmp_path):
    repo = MemoryRepository()
    store = make_store(LocalFileStorage(tmp_path), repo)
    doc = store.add(make_pdf(PAGES), "agreement.pdf")
    repo.touch_conversation("conv-1", "client", doc.document_id, "q")
    repo.history("conv-1").add_user_message("q")

    assert store.purge_older_than(datetime.now(UTC) - timedelta(hours=1)) == 0
    assert store.purge_older_than(datetime.now(UTC) + timedelta(seconds=1)) == 1

    assert store.get(doc.document_id) is None
    assert not list(tmp_path.glob("*.pdf"))
    assert repo.list_conversations("client") == []
    assert repo.history("conv-1").messages == []


def test_public_settings_endpoint():
    body = TestClient(app).get("/api/settings").json()
    assert set(body) == {"demo_notice", "retention_hours"}
