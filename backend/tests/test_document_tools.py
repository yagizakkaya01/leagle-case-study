import json

from app.services.document_tools import Evidence, linked_chunks, make_tools
from eval.documents import DOCUMENTS
from tests.pdf_factory import make_pdf, make_store


def _licence(tmp_path):
    name, pages = DOCUMENTS["license_agreement"]
    return make_store(tmp_path).add(make_pdf(pages), name)


def test_amendment_is_linked_to_the_clause_it_changes(tmp_path):
    doc = _licence(tmp_path)
    fee_clause = [c for c in doc.chunks if c.metadata["clause_number"] == "3"]
    linked = linked_chunks(doc.chunks, fee_clause)
    assert any("128,000 euros" in c.page_content for c in linked)
    assert all(c.metadata["page"] >= 7 for c in linked)


def _search(doc, **args):
    tools = make_tools(doc, Evidence())
    return next(t for t in tools if t.name == "search_document").invoke(args)


def test_clause_filter_with_no_match_searches_without_it(tmp_path):
    doc = _licence(tmp_path)
    tagged = {c.metadata["clause_category"] for c in doc.chunks}
    absent = next(c for c in ("force_majeure", "non_compete", "assignment", "insurance")
                  if c not in tagged)
    note, results = _search(doc, query="annual licence fee", clause_category=absent).split("\n", 1)
    assert absent in note and "128,000" in results


def test_page_range_still_holds_when_the_clause_filter_is_dropped(tmp_path):
    doc = _licence(tmp_path)
    tagged = {c.metadata["clause_category"] for c in doc.chunks}
    absent = next(c for c in ("force_majeure", "non_compete", "assignment", "insurance")
                  if c not in tagged)
    _, results = _search(doc, query="annual licence fee", clause_category=absent,
                         page_from=7, page_to=7).split("\n", 1)
    assert {r["page"] for r in json.loads(results) if not r.get("linked")} == {7}


def test_search_returns_linked_passages_and_records_them_as_evidence(tmp_path):
    doc = _licence(tmp_path)
    evidence = Evidence()
    search = next(t for t in make_tools(doc, evidence) if t.name == "search_document")
    results = json.loads(search.invoke({"query": "annual licence fee"}))
    linked = [r for r in results if r.get("linked")]
    assert any("128,000" in r["text"] for r in results)
    assert all(r["chunk_id"] in evidence.chunks for r in linked)
