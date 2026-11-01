import json

import pytest
from langchain_core.documents import BaseDocumentCompressor, Document
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


class _Reversing(BaseDocumentCompressor):
    def compress_documents(self, documents, query, callbacks=None):
        return [Document(d.page_content, metadata={**d.metadata, "relevance_score": 0.5})
                for d in reversed(documents)]


class _Failing(BaseDocumentCompressor):
    def compress_documents(self, documents, query, callbacks=None):
        raise RuntimeError("[410] Gone")


def _notice_chunks():
    return [Document(f"Notice rule number {n}.", metadata={"chunk_id": f"c{n}", "page": n})
            for n in range(1, 4)]


def _ids(hits):
    return [h.metadata["chunk_id"] for h in hits]


def test_reranker_decides_the_order_and_returns_the_original_chunks():
    plain = _ids(SearchIndex(_notice_chunks()).search("notice"))
    hits = SearchIndex(_notice_chunks(), reranker=_Reversing()).search("notice", k=2)
    assert _ids(hits) == plain[::-1][:2]
    assert "relevance_score" not in hits[0].metadata


def test_failed_reranker_keeps_the_merged_order():
    plain = _ids(SearchIndex(_notice_chunks()).search("notice"))
    assert _ids(SearchIndex(_notice_chunks(), reranker=_Failing()).search("notice")) == plain


def test_reranker_only_sees_chunks_the_filter_allows():
    index = SearchIndex(_notice_chunks(), reranker=_Reversing())
    assert _ids(index.search("notice", where=lambda d: d.metadata["page"] == 2)) == ["c2"]


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


NOTICES = Document("10. Notices\nNotices must be in writing and sent to the registered office.",
                   metadata={"chunk_id": "c5", "page": 5})


@pytest.mark.parametrize("quote", [
    # the whole (short) chunk plus an invented ending: it used to pass as a near match
    "10. Notices Notices must be in writing and sent to the registered office, and a notice "
    "sent by e-mail is void unless a courier confirms it within two days.",
    # a single word of the chunk quotes nothing
    "Notices",
])
def test_quote_must_be_in_the_chunk_word_for_word(quote):
    final = FinalAnswer(answer="E-mail notices are void.", chunk_id="c5", reference_text=quote)
    checked = verify(final, {"c5": NOTICES})
    assert checked.reference_text == "Notices must be in writing and sent to the registered office."


@pytest.mark.parametrize("quote", [
    "Either party may terminate this Agreement by giving sixty days written notice.",
    "The Client may terminate this Agreement by giving ninety days written notice.",
])
def test_quote_with_a_changed_word_is_replaced(quote):
    final = FinalAnswer(answer="Notice is required.", chunk_id="x-p2-c0", reference_text=quote)
    assert verify(final, {"x-p2-c0": CHUNK}).reference_text == CHUNK.page_content


def test_quote_matches_despite_case_spacing_and_punctuation():
    chunk = Document("The Client's data shall be returned\nwithin fifteen Business Days.",
                     metadata={"chunk_id": "c6", "page": 3})
    quote = "the client’s data shall be returned within fifteen business days"
    final = FinalAnswer(answer="Within fifteen Business Days.", chunk_id="c6",
                        reference_text=quote)
    assert verify(final, {"c6": chunk}).reference_text == quote


def test_short_form_line_is_kept():
    invoice = Document("Fatura No: 2024-118\nTarih: 31.08.2024\nTutar: 1.250 TL",
                       metadata={"chunk_id": "c7", "page": 1})
    final = FinalAnswer(answer="31.08.2024", chunk_id="c7", reference_text="Tarih: 31.08.2024")
    assert verify(final, {"c7": invoice}).reference_text == "Tarih: 31.08.2024"


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


CLAUSE = Document(
    page_content=(
        "Yönetim Kurulu, Şirketin devamını tehlikeye düşüren sebeplerin erken teşhisi için\n"
        "uzman bir komite kurmaya ve bu komitenin çalışma esaslarını belirlemeye\n"
        "yetkilidir (TTK m. 378).\n"
        "Madde 31 — İlanlar\n"
        "Toplantı ilanları en az 15 gün önce yapılır."
    ),
    metadata={"chunk_id": "c1", "page": 13},
)


def test_a_law_reference_in_the_answer_does_not_move_the_quote():
    final = FinalAnswer(answer="Komite kurmak zorunlu değil (TTK m. 378, Madde 31).", chunk_id="c1",
                        reference_text="uzman bir komite kurmaya")
    assert verify(final, {"c1": CLAUSE}).reference_text == "uzman bir komite kurmaya"


def test_replacement_quote_is_the_whole_wrapped_sentence():
    final = FinalAnswer(answer="Erken teşhis komitesi kurulabilir.", chunk_id="c1",
                        reference_text="Bu metin belgede hiç geçmiyor, tamamen uydurma.")
    quote = verify(final, {"c1": CLAUSE}).reference_text
    assert quote.startswith("Yönetim Kurulu") and quote.endswith("(TTK m. 378).")


def test_a_real_value_in_the_answer_still_moves_the_quote():
    final = FinalAnswer(answer="İlan 15 gün önce yapılır.", chunk_id="c1",
                        reference_text="uzman bir komite kurmaya")
    assert verify(final, {"c1": CLAUSE}).reference_text == (
        "Toplantı ilanları en az 15 gün önce yapılır.")


# --- answers with several points --------------------------------------------------

PENALTY = Document(page_content="The Tenant pays a penalty of 5,000 euros for each breach.",
                   metadata={"chunk_id": "c2", "page": 4})
NOTICE = Document(page_content="Either party may leave on 90 days notice without any reason.",
                  metadata={"chunk_id": "c3", "page": 9})
SEVERAL = {"c2": PENALTY, "c3": NOTICE}


def _risks(*claims):
    return FinalAnswer(answer="Two risks.", sources=[
        {"point": point, "chunk_id": chunk_id, "reference_text": quote}
        for point, chunk_id, quote in claims
    ])


def test_each_point_keeps_its_own_page_and_quote():
    checked = verify(_risks(("Penalty", "c2", "a penalty of 5,000 euros"),
                            ("Exit", "c3", "leave on 90 days notice")), SEVERAL)
    assert [(s.point, s.page_number, s.reference_text) for s in checked.sources] == [
        ("Penalty", 4, "a penalty of 5,000 euros"),
        ("Exit", 9, "leave on 90 days notice"),
    ]
    assert (checked.page_number, checked.reference_text) == (4, "a penalty of 5,000 euros")


def test_a_source_no_tool_returned_is_dropped():
    checked = verify(_risks(("Invented", "made-up", "anything"),
                            ("Exit", "c3", "leave on 90 days notice")), SEVERAL)
    assert [s.point for s in checked.sources] == ["Exit"] and checked.page_number == 9


def test_main_citation_is_used_when_no_listed_source_checks_out():
    final = FinalAnswer(answer="One risk.", chunk_id="c3",
                        reference_text="leave on 90 days notice",
                        sources=[{"point": "Invented", "chunk_id": "made-up"}])
    assert verify(final, SEVERAL).page_number == 9


def test_no_valid_source_at_all_is_not_shown():
    checked = verify(_risks(("Invented", "made-up", "anything")), SEVERAL)
    assert (checked.found, checked.answer, checked.sources) == (False, UNVERIFIED_ANSWER, [])


def test_the_same_passage_is_listed_once():
    checked = verify(_risks(("Penalty", "c2", "a penalty of 5,000 euros"),
                            ("Cost", "c2", "a penalty of 5,000 euros")), SEVERAL)
    assert len(checked.sources) == 1


def test_a_value_is_looked_for_in_its_own_point():
    chunk = Document(page_content="Rent is 700 euros a month.\nThe deposit is 300 euros.",
                     metadata={"chunk_id": "c4", "page": 2})
    final = FinalAnswer(answer="Rent is 700 and the deposit is 300.", sources=[
        {"point": "Deposit of 300 euros", "chunk_id": "c4", "reference_text": "Rent is 700 euros"},
    ])
    assert verify(final, {"c4": chunk}).reference_text == "The deposit is 300 euros."


def test_single_citation_is_also_listed_in_sources():
    final = FinalAnswer(answer="Ninety days.", chunk_id="x-p2-c0",
                        reference_text="ninety days written notice")
    checked = verify(final, {"x-p2-c0": CHUNK})
    assert [(s.point, s.page_number) for s in checked.sources] == [(None, 2)]
