# Next steps for search and chunking

Ideas left out on purpose. The case asks for a simple document chatbot and discourages
over-engineering, and none of these has been measured here. Each should earn its place on
the evaluation sets in [EVAL.md](EVAL.md) first. For how the assistant should behave on
legal questions, see "Next steps for a legal product" in the [README](../README.md).

## Worth trying first

- **Whole clause for the model (parent-child).** Search small chunks, but give the model
  the full clause they belong to. A clause's exceptions are often just outside a 200-word
  window. Citations would still be checked against the text the model read. A smaller
  version gives the model the neighbouring chunk of each hit.
- **Split at clause boundaries.** Split at clause and sub-clause numbers first, and use the
  word window only for what is still too long. This changes chunk ids and quote matching,
  so it needs the highlight checks repeated. A clause that crosses a page break would need
  a start and an end page on each chunk.
- **Tables, columns and scanned pages.** A layout parser such as Docling or MinerU, and OCR
  for scans (MinerU has `parse_method="ocr"`). Today a page without a text layer is only
  reported as empty, which is the gap a lawyer notices first, and reading line by line
  flattens tables, which such parsers return as rows and cells. It is also the heaviest
  change, because highlights rely on pdfplumber's character positions.
- **Word uploads.** Lawyers mostly work in Word, and only PDF is accepted. The evidence
  viewer needs pages, so a `.docx` would first be converted to PDF, for example with
  LibreOffice.

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
- **Remove repeated headers and footers.** Text repeated on every page adds noise to search,
  and a footer in capitals can replace a clause heading (see Known limitations in the
  README). Layout parsers such as MinerU mark these blocks, so they can be dropped.
- **Count tokens instead of words.** Closer to what the models actually limit.

## Reliability

- **Retry temporary errors.** A timeout or a 429 reaches the user on the first failure. A few
  retries with growing waits would suit an unstable free endpoint, but they add to the wait
  for an answer that is already slow.

## Measurement

- **Questions only a table or a scanned page can answer.** Adding these to the gold sets would
  show what is lost outside the text layer, and give the parser work above a baseline.

- **Risk-analysis questions in the gold sets.** Citing each point has only been tried by
  hand on a short synthetic contract, so how complete those answers are is not measured.
- **Keep the retrieval metrics.** Add right-page rank (top 1, top 3, MRR) to the evaluation
  runner, which needs no chat model and so uses little of the rate limit.
- **Longer, real documents.** The evaluation documents are short and synthetic. See the
  limits listed in EVAL.md.

## Tried and left out

- **A tool that reads the whole document, for risk lists.** Tried on a synthetic contract
  with 11 risks. When the model called the tool, it found 10–11 of the 11 risks; with search
  alone, 5–7 of 11. There were few runs, the model did not always call the tool (1 in 3 on an
  ordinary question), and long answers hit the 60 s timeout. Left out of scope. This was a
  one-off measurement with local code: neither the tool nor the script that measured it is
  in the repository.
