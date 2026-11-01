# Next steps for search and chunking

Ideas left out on purpose. The case asks for a simple document chatbot and discourages
over-engineering, and none of these has been measured here. Each should earn its place on
the evaluation sets in [EVAL.md](EVAL.md) first. For how the assistant should behave on
legal questions, see "Next steps for a legal product" in the [README](../README.md).

## Worth trying first

- **Whole clause for the model (parent-child).** Search small chunks, but give the model
  the full clause they belong to. A clause's exceptions are often just outside a 200-word
  window. Citations would still be checked against the text the model read.
- **Split at clause boundaries.** Split at clause and sub-clause numbers first, and use the
  word window only for what is still too long. This changes chunk ids and quote matching,
  so it needs the highlight checks repeated.
- **Tables, columns and scanned pages.** A layout parser such as Docling, and OCR for scans.
  Scanned PDFs are rejected today, which is the gap a lawyer notices first. It is also the
  heaviest change, because highlights rely on pdfplumber's character positions.
- **Word uploads.** Lawyers mostly work in Word, and only PDF is accepted. The evidence
  viewer needs pages, so a `.docx` would have to be converted to PDF first.

## Search quality

- **Soft clause filter.** Rank chunks of the asked category higher instead of excluding the
  rest. Today the filter only relaxes when it finds nothing, so a chunk tagged wrongly can
  still be missed while others of that category exist.
- **Clause categories from the model.** Tag chunks with the LLM instead of keyword rules.
  More accurate on unusual wording, but slower and costlier on upload, and the free endpoint
  is already slow.
- **Fewer, better passages.** Cut results by rerank score instead of always taking five,
  and drop near-duplicates (MMR), which overlapping chunks and risk questions produce. A
  score cut-off needs tuning per document type, or it starts hiding real clauses.
- **Remove repeated headers and footers.** Text repeated on every page adds noise to search.
- **Count tokens instead of words.** Closer to what the models actually limit.

## Measurement

- **Risk-analysis questions in the gold sets.** Citing each point has only been tried by
  hand on a short synthetic contract, so how complete those answers are is not measured.
- **Keep the retrieval metrics.** Add right-page rank (top 1, top 3, MRR) to the evaluation
  runner, which needs no chat model and so uses little of the rate limit.
- **Longer, real documents.** The evaluation documents are short and synthetic. See the
  limits listed in EVAL.md.
