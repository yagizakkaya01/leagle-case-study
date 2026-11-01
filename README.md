# Legal Document Chat

Upload a PDF, ask questions about it in a conversation, and get answers with the
**page number** and a **quote** from the document. Code checks that the quote appears word
for word in the passage it cites; it does not check that the quote supports the answer.

FastAPI + LangChain backend, React frontend, PostgreSQL chat history and Azure Blob
document storage (Azurite locally).

**Live demo: <https://leagle.yagizakkaya.com.tr>** — public, so please do not upload
confidential documents. Uploads and chats are deleted after 24 hours, and questions are
rate-limited per visitor. The demo runs the same Docker setup as below (PDFs are stored
in the Azurite emulator on the server).

| Case requirement | Status |
|---|---|
| Upload a single PDF, extract its text | ✅ page-aware extraction with `pdfplumber` |
| Ask natural-language questions, conversational flow | ✅ LangChain `RunnableWithMessageHistory` |
| Answer + page number + reference text | ✅ structured output, checked against the document by code |
| React chat UI showing answer, page and reference | ✅ the page and a one-line quote sit under each answer; "Show evidence" opens the original PDF page with the quote highlighted |
| **Bonus:** persistent chat history (PostgreSQL via LangChain) | ✅ `PostgresChatMessageHistory`, reloadable from a sidebar |
| **Bonus:** cloud document storage (Azure Blob) | ✅ Azure Blob SDK; Azurite emulator in Docker |
| **Bonus:** cloud-backed conversations | ✅ each conversation is bound to its PDF; both reload on click |
| **Bonus:** streaming responses | ✅ Server-Sent Events: tool steps live, then the verified answer ([details](#4-streaming)) |

---

## Quick start (Docker)

Requirements: Docker Desktop, and a free API key from [build.nvidia.com](https://build.nvidia.com)
(see [model selection](docs/MODEL_SELECTION.md)).

```bash
cp backend/.env.example backend/.env      # then set NVIDIA_API_KEY=nvapi-...
docker compose up --build
```

- App: <http://localhost:8080>
- API docs (Swagger): <http://localhost:8000/docs>

Compose starts four services: `frontend` (nginx serving the React build and forwarding
`/api` to the backend), `backend` (FastAPI), `db` (PostgreSQL 16) and `azurite`
(Azure Blob emulator). No Azure account is needed.

Without an API key the app still starts: uploads work with rule-based metadata, and
the chat endpoint answers `503` with a clear message.

## Local development (without Docker)

```bash
# backend (Python 3.11+)
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                  # set NVIDIA_API_KEY
uvicorn app.main:app --reload --port 8000
```

```bash
# frontend (Node 22)
cd frontend
npm install
npm run dev                                           # http://localhost:5173
```

With empty `DATABASE_URL` and `AZURE_STORAGE_CONNECTION_STRING`, history lives in
memory and PDFs in `backend/storage/`. To use the persistent backends locally, start
only the infrastructure and set the two variables shown in `.env.example`:

```bash
docker compose up -d db azurite
```

## Tests

```bash
cd backend
pytest -q          # 6 tests need PostgreSQL/Azurite and are skipped without them
ruff check .
```

**Answer quality** is measured separately against the real model with a 30-question gold
set (`python -m eval`). The latest full run, on commit `02abab5`, passed 29/30, with every
answer correct, page numbers 24/25 correct, no citations for the 5 unanswerable questions
and a prompt injection in the document ignored. That run came before the reranker and the
later changes, including the cleanup after an independent review, so **it is not a result
for the code delivered here**; after it, only a smoke test of nine hand-picked questions was
run. The gold sets have not yet been run on this code. A second, harder
set built on reported legal-RAG failure modes exposed two problems that are now fixed
(superseded terms after amendments; tool calls lost in streamed turns). Method, results,
speed and the limits of these numbers are in [docs/EVAL.md](docs/EVAL.md), including why
the one failure stays counted and an unexplained slowdown in that run.

Chat tests run against a scripted fake chat model. Setting `TEST_DATABASE_URL` and
`TEST_AZURE_CONNECTION_STRING` (values in `.github/workflows/ci.yml`) also runs the
PostgreSQL and Azure Blob variants; CI does this on every push. The frontend is checked
with `npm run lint` and `npm run build`.

---

## How it works

```
┌──────────── React (Vite) ────────────┐
│ Upload · Document card · Chat ·      │
│ Conversation sidebar                 │
└──────────────────┬───────────────────┘
                   │ REST (/api)
┌──────────────────▼───────────────────────────────────────────────┐
│ FastAPI                                                          │
│                                                                  │
│ Upload:  PDF ─► pages ─► sections ─► chunks + rule metadata      │
│                     └─► 1 LLM call: document metadata            │
│                     └─► search index (BM25 + embeddings)         │
│                                                                  │
│ Chat:    history ─► LLM ⇄ tools ─► FinalAnswer ─► verify ─► UI   │
└───────┬──────────────────────┬─────────────────────┬─────────────┘
        │                      │                     │
  NVIDIA NIM (LLM,       PostgreSQL            Azure Blob / Azurite
  embeddings)            (history, records)    (PDF files)
```

### 1. Upload: from PDF to searchable chunks

1. **Validation:** max 10 MB / 50 pages, and the file must start with `%PDF`
   (checked on the bytes, not the extension).
2. **Extraction per page** with `pdfplumber`, so every chunk keeps its page number.
3. **Sections:** headings are detected from clause patterns (`Madde 5`, `Article 5`,
   `Section 3.2`, `1.1`), all-caps lines and larger-than-body fonts. A section carries
   over a page break.
4. **Chunks** (word-based window inside each section) get rule-based metadata:
   `chunk_id`, page, section heading, clause number, clause category (payment,
   termination, governing law, … via Turkish + English keyword rules) and the clauses
   it refers to.
5. **Document metadata:** one structured LLM call extracts type, title, parties, key
   dates, governing law and a summary. Rule-based fields (outline, case numbers,
   clause counts) are never overwritten by the model, and a failed call does not fail
   the upload.
6. **Search index:** BM25 plus NVIDIA embeddings, merged with reciprocal rank fusion, then
   reordered by an NVIDIA reranker. Keyword search alone works when no embedding model is
   configured, and a failed rerank call keeps the merged order. A rerank call that hangs
   can add up to 60 s (the client's default timeout; the reranker class takes no timeout).
7. The PDF is stored under its sha256 (the same file uploaded twice is processed once).

### 2. Chat: tool calling with checked citations

The model does not get the whole document in its prompt. It **reads the document
through typed tools**:

| Tool | Use |
|---|---|
| `search_document(query, clause_category?, page_from?, page_to?)` | default for any question |
| `find_clauses(category)` | "what are the termination clauses?" |
| `get_page(page_number)` | "what does page 3 say?" |
| `get_document_info()` | overview: type, parties, dates, outline |

It finishes by calling a `FinalAnswer` tool with `answer`, `chunk_id`, `page_number`,
`reference_text` and `found`. Before anything reaches the user,
[`grounding.py`](backend/app/services/grounding.py) checks it:

- the cited chunk must be one a tool **actually returned during this question**;
- `page_number` is **taken from that chunk's metadata**, never from the model;
- `reference_text` must appear in the chunk word for word (at least three words; case,
  spacing and punctuation aside); otherwise the closest sentence of the chunk is shown;
- a date or number the answer states must be in the quote when the chunk has it;
- an answer the model marks as found but cites no chunk a tool returned is replaced by
  "could not find a passage…". An answer marked as not found is shown as written, without
  a citation. A chunk counts as the source because a tool returned it, not because its
  text proves the answer (see Known limitations).

An answer that makes several points from different passages, such as a list of risks,
also fills `sources`, one entry per point. Each entry passes the same checks and gets its
own "Show evidence" button; an entry that fails them loses its button. `page_number` and
`reference_text` always hold the first source.

The model chooses and phrases the answer; code decides what counts as its source. The
UI also lists the tool calls behind each answer ("How this answer was found").

"Show evidence" opens the original PDF on the cited page with the quote highlighted. The
same library that extracted the text locates the quote and returns boxes from its
character positions, so forms, columns, rotated and cropped pages stay aligned; pdf.js
only draws the page.

### 3. Memory and persistence

- **Conversation memory:** `RunnableWithMessageHistory` wraps the chat loop. Only the
  question and the final answer are stored (the citation travels in the message's
  `additional_kwargs` for the UI), so tool traffic never bloats the history.
- **Backends are chosen by configuration:**

  | Setting | Empty (default) | Set |
  |---|---|---|
  | `DATABASE_URL` | in-memory history | `PostgresChatMessageHistory` + `documents` / `conversations` tables |
  | `AZURE_STORAGE_CONNECTION_STRING` | `backend/storage/` | Azure Blob container |

- Each conversation is bound to its document and to an anonymous browser id
  (`client_id` in `localStorage`); other browsers cannot list, open or write to it.
- After a restart, opening a conversation rebuilds the document from Blob and the
  saved metadata, **without a new LLM call**, and loads the history from PostgreSQL.

### 4. Streaming

`POST /api/chat/stream` returns Server-Sent Events from the same chat chain (the loop
reports progress through a callback while the chain runs in a worker thread):

```
event: tool    data: {"name": "search_document", "args": {"query": "termination notice"}}
event: delta   data: {"text": "Either party may…"}
event: final   data: {answer, page_number, reference_text, found, sources, tool_calls, elapsed_seconds}
event: error   data: {"detail": "…"}
```

The UI shows each step as it happens ("Searching: termination notice") within the first
seconds, then the answer. `delta` events are parsed from the `FinalAnswer` tool call's
partial JSON. **Measured limitation:** NVIDIA's hosted endpoint delivers tool-call
arguments in one piece (the other chunks are reasoning tokens), so with this provider the
answer text arrives at once; the code streams it word by word with providers that stream
tool arguments (covered by tests). Plain-text streaming was measured too and was about
4× slower end to end, and it would give up the structured output. `final` always comes
last because verification needs the complete answer, so a streamed but unverified
answer is replaced in the UI.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/documents` | upload a PDF (multipart `file`) → document info + metadata |
| `GET` | `/api/documents/{id}/file` | the original PDF, for the evidence viewer |
| `POST` | `/api/documents/{id}/highlights` | `{page, quote}` → where the quote sits on the page, in percent of the page |
| `POST` | `/api/chat` | `{document_id, session_id, client_id, question}` → `{answer, page_number, reference_text, found, sources, tool_calls, elapsed_seconds}` |
| `POST` | `/api/chat/stream` | same body; Server-Sent Events (`tool`, `delta`, `final`, `error`) |
| `GET` | `/api/conversations?client_id=` | saved conversations, newest first |
| `GET` | `/api/conversations/{id}?client_id=` | document + stored messages with citations |
| `DELETE` | `/api/conversations/{id}?client_id=` | delete a conversation and its history |
| `GET` | `/api/settings` | demo banner text, retention, upload limit for the UI |
| `GET` | `/healthz` | liveness |

Interactive docs: `/docs`.

## Configuration

All settings live in `backend/.env` (see [`.env.example`](backend/.env.example)).

| Variable | Default | Meaning |
|---|---|---|
| `NVIDIA_API_KEY` | — | free key from build.nvidia.com; without it chat is disabled |
| `NVIDIA_MODEL` | `mistralai/mistral-large-4-1t-a52b` | chat model |
| `NVIDIA_EMBED_MODEL` | `nvidia/nemotron-3-embed-1b` | embedding model |
| `NVIDIA_RERANK_MODEL` | `nvidia/llama-nemotron-rerank-vl-1b-v2` | reranker; empty = none |
| `LLM_REASONING_EFFORT` | `low` | for reasoning models; empty for models without it |
| `LLM_MAX_TOKENS` | `4096` | includes reasoning tokens |
| `LLM_TIMEOUT_SECONDS` | `180` | per model call while answering a question (see below) |
| `METADATA_TIMEOUT_SECONDS` | `60` | the optional metadata call that the upload waits for |
| `DATABASE_URL` | empty | PostgreSQL URL for persistent history |
| `AZURE_STORAGE_CONNECTION_STRING` | empty | Azure Blob (or Azurite) for PDF files |
| `MAX_UPLOAD_MB` / `MAX_PAGES` | `10` / `50` | upload limits |
| `CORS_ORIGINS` | `http://localhost:5173` | allowed frontend origins in development |
| `CHAT_LIMIT_PER_HOUR` / `UPLOAD_LIMIT_PER_HOUR` | `60` / `20` | per client IP; `0` = unlimited |
| `TRUSTED_PROXY_HOPS` | `0` (`1` in Docker) | reverse proxies in front, used to read the real client IP |
| `RETENTION_HOURS` | `0` | delete documents and their chats after N hours; `0` = keep |
| `DEMO_NOTICE` | empty | banner text shown in the UI (public demo) |
| `LOG_LEVEL` | `INFO` | backend log level |

**Timeouts.** A model call that answers a question may take up to 180 s, and nginx waits up
to 600 s between two stream events, so a slow answer is not cut off on the way. The metadata
call keeps 60 s because the upload waits for it and works without it. About the evidence:
60 s timeouts were seen with the pushed code as well, but the 180 s value was only measured
with experimental code that is not in this repository.

## Logs

```bash
docker compose logs -f backend
```

Each request gets an id, returned in the `X-Request-ID` header and repeated on every line
it causes, so `grep 3f9a1c7e` shows one question from start to end:

```
INFO app.services.document_store [a81c04b9] document processed doc=90c9bf102b3f pages=17 chunks=45 empty_pages=0 bytes=184233 metadata_reused=False ms=2140
INFO app.services.grounding      [3f9a1c7e] quote replaced reason=not_in_chunk chunk=90c9bf102b3f-p13-c1
INFO app.services.chat           [3f9a1c7e] answer doc=90c9bf102b3f conversation=57e1ac0d-… found=True sources=3 model_turns=3 tools=search_document,find_clauses model_ms=14210 tool_ms=380
INFO app.logging_config          [3f9a1c7e] request method=POST path=/api/chat/stream status=200 ms=14650
```

| Looking for | Search for |
|---|---|
| Failed answers (with traceback; model, database or code) and model rate limits | `answer failed`, `model rate limited` |
| Requests the API refused, with the reason | `rejected status=` |
| Citations code had to correct or remove | `quote replaced`, `source dropped`, `answer rejected` |
| A quote that could not be drawn on the page | `highlight found nothing` |
| Whether the model or the tools were slow | `model_ms`, `tool_ms` on the `answer` line |

Documents can be confidential, so these lines hold counts and short ids: never the question,
the answer, a quote, a filename or a full document id. A traceback can still repeat error
text returned by the model provider.

## Project structure

```
backend/
  app/
    main.py                 FastAPI app, routers, CORS
    config.py               settings from .env
    dependencies.py         wiring of shared services (overridable in tests)
    llm.py                  ChatNVIDIA / embeddings factory, structured output helper
    schemas.py              request/response and LLM schemas
    api/                    documents, chat, conversations endpoints
    services/
      pdf_processing.py     page extraction, sections, chunks
      chunk_metadata.py     headings, clause categories, references (rules)
      document_metadata.py  document-level metadata (one LLM call)
      search_index.py       BM25 + embeddings + RRF + rerank
      document_tools.py     tools the model can call, evidence tracking
      chat.py               tool-calling loop + conversation memory
      grounding.py          citation verification
      quote_location.py     where a quote sits on its page, for the highlight
      document_store.py     upload / reload of documents
      persistence.py        in-memory or PostgreSQL repository
      file_storage.py       local folder or Azure Blob
      rate_limit.py         per-visitor limits for the public demo
  tests/                    pytest suite (fake LLM, in-memory PDFs)
  eval/                     gold set + runner for the real-model evaluation
frontend/
  src/
    api/                    REST client, anonymous client id
    components/             UploadPanel, DocumentCard, ChatPanel, ChatMessage,
                            EvidenceViewer, ConversationSidebar, DemoBanner
docs/MODEL_SELECTION.md     why these models, with live measurements
docs/EVAL.md                answer-quality evaluation against the real model
docker-compose.yml          frontend, backend, PostgreSQL, Azurite
```

## Design decisions

- **Why tool calling for a single PDF?** Putting retrieved text into the prompt and
  asking for a page number lets the model invent pages and quotes. With tools, every
  citation is traceable to a chunk the code returned, and the code verifies it.
- **Rules where rules are enough.** Headings, clause categories and case numbers
  are deterministic and free; the LLM is used once per upload for fields rules cannot
  read (parties, summary).
- **Structured output as a forced tool call.** `ChatNVIDIA.with_structured_output`
  sends an NVIDIA-specific `guided_json` field that the hosted endpoint rejects, so the
  schema is sent as a forced tool call and parsed with `PydanticToolsParser`. It works
  with any model that supports tool calling.
- **Memory class.** LangChain 1.7 marks `RunnableWithMessageHistory` and
  `InMemoryChatMessageHistory` as deprecated in favour of LangGraph persistence. They are
  kept on purpose: the case asks for LangChain's built-in memory, they work, and
  `PostgresChatMessageHistory` plugs into the same interface. Moving to LangGraph would
  add a framework for no functional gain here.
- **Model choice** is documented with live measurements in
  [docs/MODEL_SELECTION.md](docs/MODEL_SELECTION.md): Mistral Large 4 on NVIDIA's free
  endpoint, Gemma 4 31B as the tested alternative.

### Public demo safeguards

The same code runs locally and as a public demo; only configuration differs.

- **Rate limits** per client IP (sliding window, in memory) on questions and uploads.
  Behind proxies the real IP is read from `X-Forwarded-For`, counting
  `TRUSTED_PROXY_HOPS` entries from the right, so a client cannot spoof it.
- **Retention:** with `RETENTION_HOURS` set, a background task deletes expired
  documents, their files in Blob storage and all conversations about them.
- **Banner:** `DEMO_NOTICE` asks visitors not to upload confidential documents.

### Deliberately left out

Over-engineering was explicitly discouraged, so these were skipped on purpose:

- **Alembic migrations:** two small tables are created with SQLAlchemy `create_all`.
- **MMR, OCR, multi-provider LLM fallback:** useful at scale, not for one PDF.
  A failed metadata call falls back to rule-based fields; a failed chat call is reported
  to the user, who can ask again.
- **User accounts:** conversations are scoped to an anonymous browser id instead.
- **Content-level duplicate detection:** duplicates are detected by file hash only, so
  a re-saved copy of the same document counts as a new upload.

## Where the ideas come from

This project combines pieces I built and learned in earlier work:

| Piece | Earlier project |
|---|---|
| Page-aware chunking, chunk quality filter, BM25 + vector search with RRF, chat UI layout | a RAG assistant for company documents |
| Typed tools instead of free text, "the data is the truth, the narration is convenience", showing tool calls next to the answer, config/logging/compose/CI layout, model evaluation method | a natural-language query system over a PostgreSQL event store |
| Structured legal metadata, Turkish court case-number patterns, sha256-based de-duplication | indexing Turkish high-court decisions |

## Next steps for a legal product

Search and chunking ideas are listed separately in [docs/NEXT_STEPS.md](docs/NEXT_STEPS.md).

Left out on purpose: the case asks for a simple document chatbot, and these change how
the assistant behaves more than how the system is built. Each would come with its own
eval questions, mainly to check that plain factual questions do not become over-cautious.

- **Ask which party the user is.** "Can I terminate?" depends on the side. Answer for each
  party named in the document, then ask once and let conversation memory keep the reply.
- **Correct a false premise.** "Where does the 60-day notice come from?" should first say
  that the document says 30, not explain the wrong number.
- **Say when pages could not be read.** "Not in the document" can be wrong if a scanned
  annex was skipped; the answer should name the unread pages.
- **Know today's date.** "Is this contract still in force?" needs it to compare with the
  end date.
- **Stay inside the document on questions of law.** "Is this clause lawful?" should point
  to the clause and say the document cannot answer that, not recite a statute from memory.
- **Show conflicts instead of choosing.** Two clauses that disagree, with no order of
  precedence, should both be shown.
- **Cite more than one passage.** A question like "all termination grounds" spans pages,
  while each answer shows one source today.

## Known limitations

- The check confirms a quote is in the document, not that it supports the answer: an
  answer can still contradict its quote.
- Scanned PDFs without a text layer are not OCR'd; such pages (fewer than eight words of
  text) are reported as empty.
- A line in capitals at the bottom of a page, such as a `STRICTLY CONFIDENTIAL` footer, is
  taken as a heading. It then replaces the clause heading that carries over to the next
  page, so the text at the top of that page loses its clause heading and number.
- A wrapped line that starts with a date, such as "15 January 2024 between the parties", is
  still taken as a numbered heading (clause 15).
- Chat history in PostgreSQL uses one long-lived database connection that is not opened
  again: if the database restarts, chat fails until the backend is restarted. This was
  found by reading the code, not reproduced.
- The evidence viewer has no search or text selection. A quote that cannot be located
  (for example, one made only of symbols) opens its page without a highlight, with the
  quote shown above it.
- Text drawn sideways on a page is not read in order, so it answers and highlights poorly.
- The free NVIDIA endpoint has variable latency (answers usually take 5–20 s).
- Turkish is not explicitly listed for the embedding model; keyword search and the
  rule-based metadata cover Turkish documents.
