"""Repository behaviour; the PostgreSQL variant runs only when TEST_DATABASE_URL is set
(e.g. postgresql://leagle:leagle@127.0.0.1:5432/leagle with `docker compose up -d db`)."""
import os
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.services.document_store import DocumentStore
from app.services.persistence import MemoryRepository, PostgresRepository
from tests.pdf_factory import make_pdf
from tests.test_chat import PAGES

PG_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture(params=["memory", "postgres"])
def repo(request):
    if request.param == "memory":
        return MemoryRepository()
    if not PG_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    return PostgresRepository(PG_URL)


def test_document_is_rebuilt_after_restart_without_llm(repo, tmp_path):
    first = DocumentStore(tmp_path, chunk_size=200, overlap=40, max_pages=10, repository=repo)
    doc = first.add(make_pdf(PAGES), "agreement.pdf")

    # A fresh store (new process) with the same files and database.
    second = DocumentStore(tmp_path, chunk_size=200, overlap=40, max_pages=10, repository=repo)
    reloaded = second.get(doc.document_id)
    assert reloaded is not None
    assert reloaded.filename == "agreement.pdf"
    assert [c.metadata["chunk_id"] for c in reloaded.chunks] == [
        c.metadata["chunk_id"] for c in doc.chunks
    ]
    assert reloaded.metadata.clause_categories == doc.metadata.clause_categories


def test_conversation_and_history_round_trip(repo, tmp_path):
    store = DocumentStore(tmp_path, chunk_size=200, overlap=40, max_pages=10, repository=repo)
    doc = store.add(make_pdf(PAGES), "agreement.pdf")
    conv, client = str(uuid4()), f"client-{uuid4()}"

    repo.touch_conversation(conv, client, doc.document_id, title="First question")
    repo.touch_conversation(conv, client, doc.document_id, title="ignored on update")
    history = repo.history(conv)
    history.add_messages([HumanMessage("Q"), AIMessage("A", additional_kwargs={"page_number": 2})])

    [listed] = repo.list_conversations(client)
    assert (listed.id, listed.title, listed.filename) == (conv, "First question", "agreement.pdf")
    stored = repo.history(conv).messages
    assert [m.content for m in stored] == ["Q", "A"]
    assert stored[1].additional_kwargs["page_number"] == 2

    repo.delete_conversation(conv)
    assert repo.list_conversations(client) == []
    assert repo.history(conv).messages == []
