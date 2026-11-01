import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_chat_service, get_document_store, get_repository
from app.logging_config import _RequestIdFilter
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


def test_every_source_comes_back_when_a_conversation_is_reopened(setup):
    client, doc, llm = setup
    pay, end = (next(c.metadata["chunk_id"] for c in doc.chunks if c.metadata["page"] == page)
                for page in (1, 2))
    llm.replies.append(tool_call("search_document", {"query": "monthly fee terminate notice"}))
    llm.replies.append(tool_call("FinalAnswer", {"answer": "Two risks.", "sources": [
        {"point": "Fee", "chunk_id": pay, "reference_text": "a monthly fee of 2,000 euros"},
        {"point": "Exit", "chunk_id": end, "reference_text": "ninety days written notice"},
    ]}, "c2"))
    session = uuid4()
    res = client.post("/api/chat", json=_body(doc.document_id, session))
    assert res.json()["page_number"] == 1

    detail = client.get(f"/api/conversations/{session}", params={"client_id": "browser-1"}).json()
    assert [(s["point"], s["page_number"]) for s in detail["messages"][1]["sources"]] == [
        ("Fee", 1), ("Exit", 2)
    ]


def _app_log(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app"))


def test_logs_describe_an_answer_without_its_content(setup, caplog):
    caplog.set_level(logging.INFO)
    client, doc, llm = setup
    cid = next(c.metadata["chunk_id"] for c in doc.chunks if c.metadata["page"] == 2)
    llm.replies.append(tool_call("search_document", {"query": "terminate notice"}))
    llm.replies.append(tool_call("FinalAnswer", {"answer": "90 days notice.", "chunk_id": cid,
                                                 "reference_text": "made up, not in the chunk"},
                                 "c2"))
    res = client.post("/api/chat", json=_body(doc.document_id))
    assert len(res.headers["x-request-id"]) == 8

    log = _app_log(caplog)
    assert "tools=search_document" in log and "found=True sources=1 model_turns=2" in log
    assert "quote replaced reason=not_in_chunk" in log
    assert "request method=POST path=/api/chat status=200" in log
    for private in ("How can it be terminated", "90 days", "ninety days", "agreement.pdf",
                    doc.document_id):
        assert private not in log


def test_a_streamed_answer_logs_under_its_request_id(setup, caplog):
    caplog.set_level(logging.INFO)
    caplog.handler.addFilter(_RequestIdFilter())
    client, doc, llm = setup
    llm.replies.append(tool_call("FinalAnswer", {"answer": "No.", "found": False}))

    res = client.post("/api/chat/stream", json=_body(doc.document_id))
    answer = next(r for r in caplog.records if r.getMessage().startswith("answer doc="))
    assert answer.request_id == res.headers["x-request-id"]


def test_model_failure_is_logged_with_its_cause(setup, caplog):
    client, doc, _ = setup
    class Broken:
        def ask(self, *_):
            raise TimeoutError("no reply")
    app.dependency_overrides[get_chat_service] = Broken

    assert client.post("/api/chat", json=_body(doc.document_id)).status_code == 502
    failure = next(r for r in caplog.records if "model call failed" in r.getMessage())
    assert "error=TimeoutError" in failure.getMessage() and failure.exc_info


def test_rejections_and_document_paths_are_logged(setup, caplog):
    caplog.set_level(logging.INFO)
    client, doc, _ = setup
    assert client.post(f"/api/documents/{doc.document_id}/highlights",
                       json={"page": 2, "quote": "nothing like this exists"}).json() == []
    assert client.post("/api/chat", json=_body("missing")).status_code == 404

    log = _app_log(caplog)
    assert "highlight found nothing" in log and "rejected status=404" in log
    assert f"path=/api/documents/{doc.document_id[:12]}/highlights" in log
    assert doc.document_id not in log


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


def test_stream_endpoint_sends_sse_and_saves_conversation(setup):
    client, doc, llm = setup
    llm.replies.append(tool_call("FinalAnswer", {"answer": "No mention of salaries.",
                                                 "found": False}))
    session = uuid4()
    res = client.post("/api/chat/stream", json=_body(doc.document_id, session))
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    frames = [f for f in res.text.split("\n\n") if f]
    assert frames[-1].startswith("event: final")
    assert '"answer": "No mention of salaries."' in frames[-1]
    listed = client.get("/api/conversations", params={"client_id": "browser-1"}).json()
    assert [c["session_id"] for c in listed] == [str(session)]


def test_stream_endpoint_reports_llm_failure_as_error_event(setup):
    client, doc, _ = setup  # no scripted replies -> the model call fails
    res = client.post("/api/chat/stream", json=_body(doc.document_id))
    assert res.status_code == 200
    assert res.text.strip().startswith("event: error")


def test_stream_endpoint_validates_before_streaming(setup):
    client, _, _ = setup
    assert client.post("/api/chat/stream", json=_body("missing")).status_code == 404


class _RateLimitedChat:
    def ask(self, *_):
        raise RuntimeError("[429] Too Many Requests")

    def ask_stream(self, *_):
        raise RuntimeError("[429] Too Many Requests")
        yield


def test_rate_limit_is_explained_instead_of_a_generic_failure(setup):
    client, doc, _ = setup
    app.dependency_overrides[get_chat_service] = _RateLimitedChat

    res = client.post("/api/chat", json=_body(doc.document_id))
    assert res.status_code == 503 and "rate limited" in res.json()["detail"]

    stream = client.post("/api/chat/stream", json=_body(doc.document_id))
    assert "event: error" in stream.text and "rate limited" in stream.text
