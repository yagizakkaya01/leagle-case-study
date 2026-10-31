from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_chat_service, get_document_store, get_repository
from app.main import app
from app.services.chat import ChatService
from app.services.persistence import MemoryRepository
from tests.fakes import ScriptedChatModel, tool_call
from tests.pdf_factory import make_pdf, make_store
from tests.test_chat import PAGES


@pytest.fixture
def setup(tmp_path):
    repo = MemoryRepository()
    store = make_store(tmp_path, repo)
    doc = store.add(make_pdf(PAGES), "agreement.pdf")
    llm = ScriptedChatModel(replies=[], seen=[], tool_choices=[])
    app.dependency_overrides[get_document_store] = lambda: store
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_chat_service] = lambda: ChatService(llm, repo.history)
    yield TestClient(app), doc, llm
    app.dependency_overrides.clear()


def _body(doc_id, session=None, client="browser-1", question="How can it be terminated?"):
    return {"document_id": doc_id, "session_id": str(session or uuid4()),
            "client_id": client, "question": question}


def test_chat_saves_conversation_and_it_can_be_reopened(setup):
    client, doc, llm = setup
    cid = next(c.metadata["chunk_id"] for c in doc.chunks if c.metadata["page"] == 2)
    llm.replies.append(tool_call("search_document", {"query": "terminate"}))
    llm.replies.append(tool_call("FinalAnswer", {"answer": "90 days notice.", "chunk_id": cid,
                                                 "reference_text": "ninety days written notice"},
                                 "c2"))
    session = uuid4()
    res = client.post("/api/chat", json=_body(doc.document_id, session))
    assert res.status_code == 200 and res.json()["page_number"] == 2

    listed = client.get("/api/conversations", params={"client_id": "browser-1"}).json()
    assert [(c["session_id"], c["title"], c["filename"]) for c in listed] == [
        (str(session), "How can it be terminated?", "agreement.pdf")
    ]
    detail = client.get(f"/api/conversations/{session}", params={"client_id": "browser-1"}).json()
    assert detail["document"]["document_id"] == doc.document_id
    assert [(m["role"], m["page_number"]) for m in detail["messages"]] == [
        ("user", None), ("assistant", 2)
    ]
    assert detail["messages"][1]["reference_text"] == "ninety days written notice"


def test_conversations_are_private_to_their_client(setup):
    client, doc, llm = setup
    llm.replies.append(tool_call("FinalAnswer", {"answer": "No.", "found": False}))
    session = uuid4()
    client.post("/api/chat", json=_body(doc.document_id, session))

    assert client.get("/api/conversations", params={"client_id": "intruder"}).json() == []
    assert client.get(f"/api/conversations/{session}",
                      params={"client_id": "intruder"}).status_code == 404
    other = client.post("/api/chat", json=_body(doc.document_id, session, client="intruder"))
    assert other.status_code == 403


def test_delete_conversation(setup):
    client, doc, llm = setup
    llm.replies.append(tool_call("FinalAnswer", {"answer": "No.", "found": False}))
    session = uuid4()
    client.post("/api/chat", json=_body(doc.document_id, session))
    params = {"client_id": "browser-1"}
    assert client.delete(f"/api/conversations/{session}", params=params).status_code == 204
    assert client.get("/api/conversations", params=params).json() == []


def test_chat_errors(setup):
    client, doc, _ = setup
    assert client.post("/api/chat", json=_body("missing")).status_code == 404
    assert client.post("/api/chat", json=_body(doc.document_id, question="")).status_code == 422
    bad_session = {**_body(doc.document_id), "session_id": "not-a-uuid"}
    assert client.post("/api/chat", json=bad_session).status_code == 422
    assert client.post("/api/chat", json=_body(doc.document_id)).status_code == 502  # no replies
    app.dependency_overrides[get_chat_service] = lambda: None
    assert client.post("/api/chat", json=_body(doc.document_id)).status_code == 503
