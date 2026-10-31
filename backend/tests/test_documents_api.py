import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_document_store
from app.main import app
from app.services.document_store import DocumentStore
from tests.pdf_factory import make_pdf
from tests.test_pdf_processing import CLAUSE


@pytest.fixture
def client(tmp_path):
    store = DocumentStore(tmp_path, chunk_size=200, overlap=40, max_pages=50)
    app.dependency_overrides[get_document_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _upload(client, data: bytes, name="lease.pdf"):
    return client.post("/api/documents", files={"file": (name, data, "application/pdf")})


def test_upload_returns_document_info(client):
    res = _upload(client, make_pdf([CLAUSE, ""]))
    assert res.status_code == 200
    body = res.json()
    assert body["filename"] == "lease.pdf"
    assert body["page_count"] == 2
    assert body["chunk_count"] == 1
    assert body["empty_pages"] == [2]
    assert len(body["document_id"]) == 64


def test_same_file_gets_same_id(client):
    data = make_pdf([CLAUSE])
    first = _upload(client, data).json()
    second = _upload(client, data).json()
    assert first["document_id"] == second["document_id"]


def test_rejects_non_pdf(client):
    res = _upload(client, b"hello", name="notes.txt")
    assert res.status_code == 400
    assert res.json()["detail"] == "Only PDF files are accepted."


def test_rejects_pdf_without_text(client):
    res = _upload(client, make_pdf(["", ""]))
    assert res.status_code == 422
