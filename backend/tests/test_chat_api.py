from fastapi.testclient import TestClient

from app.dependencies import get_chat_service, get_document_store
from app.main import app
from app.services.chat import ChatService, InMemoryHistories
from app.services.document_store import DocumentStore
from tests.fakes import ScriptedChatModel, tool_call
from tests.pdf_factory import make_pdf
from tests.test_chat import PAGES


def _client(tmp_path, chat):
    store = DocumentStore(tmp_path, chunk_size=200, overlap=40, max_pages=10)
    doc = store.add(make_pdf(PAGES), "agreement.pdf")
    app.dependency_overrides[get_document_store] = lambda: store
    app.dependency_overrides[get_chat_service] = lambda: chat
    return TestClient(app), doc


def _body(doc_id, question="How can it be terminated?"):
    return {"document_id": doc_id, "session_id": "s1", "question": question}


def test_chat_returns_answer(tmp_path):
    llm = ScriptedChatModel(replies=[tool_call("FinalAnswer", {"answer": "No.", "found": False})],
                            seen=[], tool_choices=[])
    client, doc = _client(tmp_path, ChatService(llm, InMemoryHistories()))
    res = client.post("/api/chat", json=_body(doc.document_id))
    app.dependency_overrides.clear()
    assert res.status_code == 200
    assert res.json()["answer"] == "No." and res.json()["found"] is False


def test_chat_errors(tmp_path):
    client, doc = _client(tmp_path, None)
    assert client.post("/api/chat", json=_body(doc.document_id)).status_code == 503
    app.dependency_overrides[get_chat_service] = lambda: ChatService(
        ScriptedChatModel(replies=[], seen=[], tool_choices=[]), InMemoryHistories())
    assert client.post("/api/chat", json=_body("missing")).status_code == 404
    assert client.post("/api/chat", json=_body(doc.document_id, "")).status_code == 422
    assert client.post("/api/chat", json=_body(doc.document_id)).status_code == 502  # LLM fails
    app.dependency_overrides.clear()
