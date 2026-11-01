import json

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage

from app.schemas import FinalAnswer
from app.services.chat import ChatService
from app.services.document_store import DocumentStore
from app.services.file_storage import LocalFileStorage
from app.services.grounding import UNVERIFIED_ANSWER, verify
from app.services.persistence import MemoryRepository
from app.services.search_index import SearchIndex, rrf_merge
from tests.fakes import ScriptedChatModel, tool_call
from tests.pdf_factory import make_pdf

PAGES = [
    "SERVICE AGREEMENT\n1. Payment\nThe Client shall pay a monthly fee of 2,000 euros within "
    "thirty days of receiving each invoice.",
    "2. Termination\nEither party may terminate this Agreement by giving ninety days written "
    "notice to the other party.",
]


@pytest.fixture
def doc(tmp_path):
    store = DocumentStore(LocalFileStorage(tmp_path), chunk_size=200, overlap=40, max_pages=10)
    return store.add(make_pdf(PAGES), "agreement.pdf")


def _chunk_id(doc, page):
    return next(c.metadata["chunk_id"] for c in doc.chunks if c.metadata["page"] == page)


# --- search -------------------------------------------------------------------

def test_rrf_merge_rewards_items_ranked_by_both_lists():
    assert rrf_merge(["a", "b", "c"], ["c", "a"])[:2] == ["a", "c"]


def test_keyword_search_finds_termination_and_respects_filter(doc):
    hits = doc.index.search("how can the agreement be terminated notice", k=1)
    assert hits[0].metadata["page"] == 2
    page_one_only = doc.index.search("terminate notice", where=lambda d: d.metadata["page"] == 1)
    assert all(h.metadata["page"] == 1 for h in page_one_only)


def test_search_index_without_chunks_returns_nothing():
    assert SearchIndex([]).search("anything") == []


# --- grounding -----------------------------------------------------------------

CHUNK = Document(
    page_content="Either party may terminate this Agreement by giving ninety days written notice.",
    metadata={"chunk_id": "x-p2-c0", "page": 2},
)


def test_verify_takes_page_from_metadata_not_from_model():
    final = FinalAnswer(answer="90 days notice", found=True, chunk_id="x-p2-c0",
                        page_number=7, reference_text="giving ninety days written notice")
    checked = verify(final, {"x-p2-c0": CHUNK})
    assert checked.page_number == 2
    assert checked.reference_text == "giving ninety days written notice"


def test_verify_replaces_invented_quote_with_chunk_sentence():
    final = FinalAnswer(answer="90 days", found=True, chunk_id="x-p2-c0",
                        reference_text="The contract ends automatically after one year.")
    checked = verify(final, {"x-p2-c0": CHUNK})
    assert checked.reference_text == CHUNK.page_content


def test_verify_rejects_chunk_the_tools_never_returned():
    final = FinalAnswer(answer="Invented", found=True, chunk_id="made-up", page_number=1)
    checked = verify(final, {"x-p2-c0": CHUNK})
    assert (checked.found, checked.answer, checked.page_number) == (False, UNVERIFIED_ANSWER, None)


def test_verify_keeps_not_found_answer_without_citation():
    final = FinalAnswer(answer="The document does not mention salaries.", found=False)
    checked = verify(final, {})
    assert checked.answer == final.answer and checked.reference_text is None


# --- chat loop + memory ------------------------------------------------------------

def test_chat_runs_tool_then_returns_verified_answer(doc):
    cid = _chunk_id(doc, 2)
    llm = ScriptedChatModel(replies=[
        tool_call("search_document", {"query": "termination notice"}),
        tool_call("FinalAnswer", {"answer": "With 90 days written notice.", "chunk_id": cid,
                                  "page_number": 1, "reference_text": "ninety days written notice"},
                  call_id="c2"),
    ], seen=[], tool_choices=[])
    chat = ChatService(llm, MemoryRepository().history)
    answer = chat.ask(doc, "s1", "How can it be terminated?")

    assert answer.found is True
    assert answer.page_number == 2  # corrected from the model's 1
    assert answer.reference_text == "ninety days written notice"
    assert [c.name for c in answer.tool_calls] == ["search_document"]


def test_conversation_history_is_kept_per_session(doc):
    replies = [
        tool_call("FinalAnswer", {"answer": "First answer", "found": False}),
        tool_call("FinalAnswer", {"answer": "Second answer", "found": False}),
        tool_call("FinalAnswer", {"answer": "Other session", "found": False}),
    ]
    llm = ScriptedChatModel(replies=replies, seen=[], tool_choices=[])
    chat = ChatService(llm, MemoryRepository().history)
    chat.ask(doc, "s1", "first question")
    chat.ask(doc, "s1", "follow-up")
    chat.ask(doc, "s2", "unrelated")

    second_turn = llm.seen[1]
    assert [m.content for m in second_turn if isinstance(m, (HumanMessage, AIMessage))] == [
        "first question", "First answer", "follow-up",
    ]
    third_turn = llm.seen[2]
    assert [m.content for m in third_turn if isinstance(m, HumanMessage)] == ["unrelated"]


def test_last_round_forces_final_answer(doc):
    llm = ScriptedChatModel(replies=[
        tool_call("search_document", {"query": "a"}, "c1"),
        tool_call("search_document", {"query": "b"}, "c2"),
        tool_call("search_document", {"query": "c"}, "c3"),
        tool_call("FinalAnswer", {"answer": "Stopped", "found": False}, "c4"),
    ], seen=[], tool_choices=[])
    answer = ChatService(llm, MemoryRepository().history).ask(doc, "s1", "q")
    assert llm.tool_choices[-1] == "FinalAnswer"
    assert answer.answer == "Stopped" and len(answer.tool_calls) == 3


def test_plain_text_reply_is_never_marked_as_found(doc):
    llm = ScriptedChatModel(replies=[AIMessage(content="Hello! Ask me about the document.")],
                            seen=[], tool_choices=[])
    answer = ChatService(llm, MemoryRepository().history).ask(doc, "s1", "hi")
    assert answer.found is False and answer.answer.startswith("Hello")


def test_malformed_final_answer_drops_citation(doc):
    bad = tool_call("FinalAnswer", {"answer": "x", "page_number": "two"})
    llm = ScriptedChatModel(replies=[bad], seen=[], tool_choices=[])
    answer = ChatService(llm, MemoryRepository().history).ask(doc, "s1", "q")
    assert answer.found is False and answer.page_number is None


# --- streaming ------------------------------------------------------------------------

def test_stream_emits_tool_steps_answer_text_and_verified_final(doc):
    cid = _chunk_id(doc, 2)
    llm = ScriptedChatModel(replies=[
        tool_call("search_document", {"query": "termination notice"}),
        tool_call("FinalAnswer", {"answer": "With ninety days written notice.", "chunk_id": cid,
                                  "page_number": 9, "reference_text": "ninety days written notice"},
                  call_id="c2"),
    ], seen=[], tool_choices=[])
    chat = ChatService(llm, MemoryRepository().history)
    events = list(chat.ask_stream(doc, "s1", "How can it be terminated?"))

    kinds = [e["type"] for e in events]
    assert kinds[0] == "tool" and kinds[-1] == "final"
    assert events[0]["args"] == {"query": "termination notice"}
    streamed = "".join(e["text"] for e in events if e["type"] == "delta")
    assert streamed == "With ninety days written notice."
    assert kinds.count("delta") > 1  # arrived in pieces
    final = events[-1]["answer"]
    assert final.page_number == 2 and final.found is True


def test_stream_final_replaces_unverified_streamed_text(doc):
    llm = ScriptedChatModel(replies=[
        tool_call("FinalAnswer", {"answer": "Invented clause text.", "chunk_id": "nope"}),
    ], seen=[], tool_choices=[])
    events = list(ChatService(llm, MemoryRepository().history).ask_stream(doc, "s1", "q"))
    assert "Invented" in "".join(e.get("text", "") for e in events)
    assert events[-1]["answer"].answer == UNVERIFIED_ANSWER


def test_stream_raises_when_the_model_fails(doc):
    llm = ScriptedChatModel(replies=[], seen=[], tool_choices=[])
    with pytest.raises(IndexError):
        list(ChatService(llm, MemoryRepository().history).ask_stream(doc, "s1", "q"))


def test_streamed_turn_sends_its_tool_calls_back_to_the_provider(doc):
    """Regression: ChatNVIDIA only forwards additional_kwargs["tool_calls"]; a streamed
    turn without it produced a tool result with no matching call (HTTP 400)."""
    from langchain_nvidia_ai_endpoints._utils import convert_message_to_dict

    from app.services.chat import _stream_reply

    llm = ScriptedChatModel(replies=[tool_call("search_document", {"query": "aylık ücret"})],
                            seen=[], tool_choices=[])
    turn = _stream_reply(llm, [HumanMessage("Aylık ücret ne kadar?")], emit=lambda _: None)
    sent = convert_message_to_dict(turn)
    assert sent["tool_calls"][0]["function"]["name"] == "search_document"
    assert json.loads(sent["tool_calls"][0]["function"]["arguments"]) == {"query": "aylık ücret"}


def test_replacement_quote_keeps_the_value_after_a_label():
    chunk = Document(
        page_content="12345678901 Discharge Date : 31.08.2024\nAdmission Date : 26.08.2024",
        metadata={"chunk_id": "c1", "page": 1},
    )
    final = FinalAnswer(answer="31.08.2024", chunk_id="c1", reference_text="left on 31.08.2024")
    checked = verify(final, {"c1": chunk})
    assert checked.reference_text == "12345678901 Discharge Date : 31.08.2024"


FORM = Document(
    page_content="Discharge Date : 31.08.2024\nExit Type : Recovered and discharged",
    metadata={"chunk_id": "c1", "page": 1},
)


def test_quote_moves_to_the_line_stating_the_answers_date():
    final = FinalAnswer(answer="Discharged on 31/08/2024.", chunk_id="c1",
                        reference_text="Exit Type : Recovered and discharged")
    assert verify(final, {"c1": FORM}).reference_text == "Discharge Date : 31.08.2024"


def test_quote_stays_when_it_already_states_the_date():
    final = FinalAnswer(answer="31.08.2024", chunk_id="c1",
                        reference_text="Discharge Date : 31.08.2024")
    assert verify(final, {"c1": FORM}).reference_text == "Discharge Date : 31.08.2024"


def test_quote_stays_when_the_chunk_lacks_the_number():
    # A value the model worked out is not in the text; there is no better line to show.
    final = FinalAnswer(answer="In total 128 days.", chunk_id="c1",
                        reference_text="Exit Type : Recovered and discharged")
    assert verify(final, {"c1": FORM}).reference_text == "Exit Type : Recovered and discharged"
