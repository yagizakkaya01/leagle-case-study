# Legal Document Chat

Upload a PDF, ask questions about it in a conversation, and get answers with the
**page number** and a **verified quote** from the document.

FastAPI + LangChain backend, React frontend, PostgreSQL chat history and Azure Blob
document storage (Azurite locally).

| Case requirement | Status |
|---|---|
| Upload a single PDF, extract its text | ✅ page-aware extraction with `pdfplumber` |
| Ask natural-language questions, conversational flow | ✅ LangChain `RunnableWithMessageHistory` |
| Answer + page number + reference text | ✅ structured output, checked against the document by code |
| React chat UI showing answer, page and reference | ✅ |
| **Bonus:** persistent chat history (PostgreSQL via LangChain) | ✅ `PostgresChatMessageHistory`, reloadable from a sidebar |
| **Bonus:** cloud document storage (Azure Blob) | ✅ Azure Blob SDK; Azurite emulator in Docker |
| **Bonus:** cloud-backed conversations | ✅ each conversation is bound to its PDF; both reload on click |
| **Bonus:** streaming responses | ⏳ not yet |

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
pytest -q          # 56 tests; 4 need PostgreSQL/Azurite and are skipped without them
ruff check .
```

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
   termination, governing law, … via Turkish + English keyword rules), amount/date
   flags and defined terms.
5. **Document metadata:** one structured LLM call extracts type, title, parties, key
   dates, governing law and a summary. Rule-based fields (outline, case numbers,
   clause counts) are never overwritten by the model, and a failed call does not fail
   the upload.
6. **Search index:** BM25 plus NVIDIA embeddings, merged with reciprocal rank fusion.
   Keyword search alone works when no embedding model is configured.
7. The PDF is stored under its sha256 (the same file uploaded twice is processed once).

### 2. Chat: tool calling with verified citations

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
- `reference_text` must really appear in the chunk (`rapidfuzz` ≥ 85); otherwise the
  closest sentence of the chunk is shown;
- a claim with no supporting chunk is replaced by "could not find a passage…".

The model chooses and phrases the answer; code decides what counts as its source. The
UI also lists the tool calls behind each answer ("How this answer was found").

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

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/documents` | upload a PDF (multipart `file`) → document info + metadata |
| `POST` | `/api/chat` | `{document_id, session_id, client_id, question}` → `{answer, page_number, reference_text, found, tool_calls, elapsed_seconds}` |
| `GET` | `/api/conversations?client_id=` | saved conversations, newest first |
| `GET` | `/api/conversations/{id}?client_id=` | document + stored messages with citations |
| `DELETE` | `/api/conversations/{id}?client_id=` | delete a conversation and its history |
| `GET` | `/healthz` | liveness |

Interactive docs: `/docs`.

## Configuration

All settings live in `backend/.env` (see [`.env.example`](backend/.env.example)).

| Variable | Default | Meaning |
|---|---|---|
| `NVIDIA_API_KEY` | — | free key from build.nvidia.com; without it chat is disabled |
| `NVIDIA_MODEL` | `mistralai/mistral-large-4-1t-a52b` | chat model |
| `NVIDIA_EMBED_MODEL` | `nvidia/nemotron-3-embed-1b` | embedding model |
| `LLM_REASONING_EFFORT` | `low` | for reasoning models; empty for models without it |
| `LLM_MAX_TOKENS` | `4096` | includes reasoning tokens |
| `DATABASE_URL` | empty | PostgreSQL URL for persistent history |
| `AZURE_STORAGE_CONNECTION_STRING` | empty | Azure Blob (or Azurite) for PDF files |
| `MAX_UPLOAD_MB` / `MAX_PAGES` | `10` / `50` | upload limits |
| `CORS_ORIGINS` | `http://localhost:5173` | allowed frontend origins in development |

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
      chunk_metadata.py     headings, clause categories, flags (rules)
      document_metadata.py  document-level metadata (one LLM call)
      search_index.py       BM25 + embeddings + RRF
      document_tools.py     tools the model can call, evidence tracking
      chat.py               tool-calling loop + conversation memory
      grounding.py          citation verification
      document_store.py     upload / reload of documents
      persistence.py        in-memory or PostgreSQL repository
      file_storage.py       local folder or Azure Blob
  tests/                    pytest suite (fake LLM, in-memory PDFs)
frontend/
  src/
    api/                    REST client, anonymous client id
    components/             UploadPanel, DocumentCard, ChatPanel, ChatMessage,
                            ConversationSidebar
docs/MODEL_SELECTION.md     why these models, with live measurements
docker-compose.yml          frontend, backend, PostgreSQL, Azurite
```

## Design decisions

- **Why tool calling for a single PDF?** Putting retrieved text into the prompt and
  asking for a page number lets the model invent pages and quotes. With tools, every
  citation is traceable to a chunk the code returned, and the code verifies it.
- **Rules where rules are enough.** Headings, clause categories, case numbers and flags
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

### Deliberately left out

Over-engineering was explicitly discouraged, so these were skipped on purpose:

- **Alembic migrations:** two small tables are created with SQLAlchemy `create_all`.
- **Rerankers, MMR, OCR, multi-provider LLM fallback:** useful at scale, not for one PDF.
  Transient LLM errors are retried; a failed metadata call falls back to rule-based
  fields.
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

## Known limitations

- Scanned PDFs without a text layer are not OCR'd; such pages are reported as empty.
- The free NVIDIA endpoint has variable latency (answers usually take 5–20 s).
- Turkish is not explicitly listed for the embedding model; keyword search and the
  rule-based metadata cover Turkish documents.
