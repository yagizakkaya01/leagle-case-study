# System diagrams

Models of the system as it is built, drawn from the code in `backend/app` and
`frontend/src`. They are written in Mermaid, so GitHub renders them and they can be
reviewed as text.

| # | Diagram | Question it answers | 4+1 view |
|---|---|---|---|
| 1 | [Context](#1-context-model) | What is inside the system, and what is around it? | – |
| 2 | [Use cases](#2-use-cases) | What can each actor do? | Scenarios |
| 3 | [Activity: upload](#3-activity-uploading-a-pdf) | What happens to a PDF, and when is it refused? | Process |
| 4 | [Activity: citation check](#4-activity-checking-a-citation) | How does a model answer become a verified one? | Process |
| 5 | [Class: backend](#5-class-diagram-backend) (2 parts) | Which objects carry the work? | Logical |
| 6 | [Class: stored data](#6-class-diagram-stored-data) | What survives a restart? | Logical |
| 7 | [Sequence: ask a question](#7-sequence-asking-a-question) | Who calls whom during a streamed answer? | Process |
| 8 | [Sequence: reopen a conversation](#8-sequence-reopening-a-conversation) | How do a document and its chat come back? | Process |
| 9 | [State: document](#9-state-machine-a-document) | What states does an uploaded document go through? | Process |
| 10 | [State: question](#10-state-machine-a-question) | How does the tool loop end? | Process |
| 11 | [Data flow](#11-data-flow-level-1) (3 parts) | Where does each piece of data go? | Logical |
| 12 | [Layered architecture](#12-layered-architecture) | How is the code organised? | Development |
| 13 | [Deployment](#13-deployment) | What runs where? | Physical |

## 1. Context model

PostgreSQL and Blob Storage count as neighbouring systems here because the case treats
them as external cloud services. Without their settings, the app keeps the same data in
process memory and in a local folder.

```mermaid
flowchart LR
    user["«actor»<br/>Legal professional<br/>(anonymous browser)"]
    system(["«system»<br/><b>Leagle Document Chat</b>"])
    nim["«external system»<br/>NVIDIA NIM<br/>chat · embeddings · rerank"]
    pg[("«external system»<br/>PostgreSQL")]
    blob[("«external system»<br/>Azure Blob Storage<br/>or Azurite")]

    user -- "PDF, questions,<br/>conversation choice" --> system
    system -- "document summary, tool steps,<br/>answer + page + quote, highlighted page" --> user
    system -- "prompts, tool results,<br/>chunks, queries" --> nim
    nim -- "tool calls, final answer,<br/>vectors, rankings" --> system
    system <-- "document records,<br/>conversations, messages" --> pg
    system <-- "original PDF files" --> blob
```

## 2. Use cases

Mermaid has no use case diagram, so this one is a flowchart: rounded nodes are use cases
and the box is the system boundary.

```mermaid
flowchart LR
    visitor["«actor»<br/>Visitor"]
    timer["«actor»<br/>Retention timer"]
    nim["«actor»<br/>NVIDIA NIM"]

    subgraph system["Leagle Document Chat"]
        direction TB
        uc1(["Upload a PDF"])
        uc2(["Read document summary"])
        uc3(["Ask a question"])
        uc4(["Read answer, page and quote"])
        uc5(["Show evidence on the PDF page"])
        uc6(["See how the answer was found"])
        uc7(["Start a new chat on the document"])
        uc8(["Browse saved conversations"])
        uc9(["Reopen a conversation"])
        uc10(["Delete a conversation"])
        uc11(["Purge expired documents"])
        inc1(["Extract document metadata"])
        inc2(["Verify citations"])
        inc3(["Restore document from storage"])
    end

    visitor --- uc1 & uc2 & uc3 & uc7 & uc8 & uc9 & uc10
    timer --- uc11

    uc1 -. "«include»" .-> inc1
    uc3 -. "«include»" .-> inc2
    uc3 -. "«include»" .-> uc4
    uc9 -. "«include»" .-> inc3
    uc5 -. "«extend»" .-> uc4
    uc6 -. "«extend»" .-> uc4

    inc1 --- nim
    uc3 --- nim
```

## 3. Activity: uploading a PDF

```mermaid
flowchart TD
    start(( )) --> limit{"Over the hourly<br/>upload limit?"}
    limit -- yes --> e429["429 Too Many Requests"]
    limit -- no --> size{"Larger than<br/>MAX_UPLOAD_MB?"}
    size -- yes --> e413["413 Too Large"]
    size -- no --> magic{"Starts with<br/>%PDF bytes?"}
    magic -- no --> e400a["400 Only PDF accepted"]
    magic -- yes --> hash["Compute sha256 = document id"]
    hash --> cached{"Already in<br/>memory?"}
    cached -- yes --> done["Return DocumentInfo"]
    cached -- no --> lookup["Look up an earlier record"]
    lookup --> open{"Readable PDF within<br/>MAX_PAGES?"}
    open -- no --> e400b["400 Unreadable or too many pages"]
    open -- yes --> extract["Extract text page by page"]
    extract --> sections["Detect headings and sections"]
    sections --> chunks["Split into chunks,<br/>add rule-based metadata"]
    chunks --> any{"Any valid<br/>chunks?"}
    any -- no --> e422["422 No extractable text<br/>(nothing is stored)"]
    any -- yes --> known{"Metadata known<br/>from earlier run?"}
    known -- yes --> index
    known -- no --> rules["Collect rule-based fields"]
    rules --> llm{"LLM metadata call<br/>succeeds?"}
    llm -- yes --> merge["Merge LLM fields"]
    llm -- no --> keep["Keep rule-based fields only"]
    merge --> index
    keep --> index
    index["Build search index<br/>BM25 + embeddings if available"]
    index --> save["Save PDF to file storage<br/>Save record to repository<br/>Cache in memory"]
    save --> done
    done --> finish(((" ")))
    e429 --> finish
    e413 --> finish
    e400a --> finish
    e400b --> finish
    e422 --> finish
```

## 4. Activity: checking a citation

`grounding.verify()` runs on every answer before the user sees it. The model chooses the
wording; this code decides what counts as its source.

```mermaid
flowchart TD
    start(( )) --> found{"Model says<br/>found = true?"}
    found -- no --> notfound["Return the answer<br/>with no citation, found = false"]
    found -- yes --> claims["Take the sources list (max 10),<br/>or the main citation if it is empty"]
    claims --> next["Next claim"]
    next --> returned{"Did a tool return<br/>this chunk during<br/>this question?"}
    returned -- no --> drop["Drop the claim"]
    returned -- yes --> fuzzy{"Quote in chunk word for word?<br/>at least 3 words"}
    fuzzy -- no --> closest["Use the chunk's<br/>closest sentence"]
    fuzzy -- yes --> facts
    closest --> facts{"Chunk has a date or number<br/>from the answer that<br/>the quote lacks?"}
    facts -- yes --> stating["Use the sentence<br/>stating that value"]
    facts -- no --> page
    stating --> page["Trim to 600 characters<br/>Take page from chunk metadata<br/>Skip duplicates"]
    page --> more{"More claims?"}
    drop --> more
    more -- yes --> next
    more -- no --> any{"Any citation<br/>left?"}
    any -- yes --> ok["Return answer, found = true,<br/>one Source per point"]
    any -- no --> retried{"Main chunk_id<br/>already tried?"}
    retried -- no --> main["Check the main chunk_id<br/>and reference_text as one claim"]
    main --> next
    retried -- yes --> reject["Replace the answer with<br/>“could not find a passage”,<br/>found = false"]
    notfound --> finish(((" ")))
    ok --> finish
    reject --> finish
```

## 5. Class diagram: backend

Two parts, one for each main flow. `document_tools` and `grounding` are modules of
functions, not classes.

**Answering a question**

```mermaid
classDiagram
    direction LR
    class ChatService {
        -llm: BaseChatModel
        -chain: RunnableWithMessageHistory
        +ask(doc, conversation_id, question, emit) ChatAnswer
        +ask_stream(doc, conversation_id, question) Iterator
        -_answer(inputs) dict
    }
    class document_tools {
        <<module>>
        +make_tools(doc, evidence) list
        +linked_chunks(all_chunks, hits) list
    }
    class Evidence {
        +chunks: dict
        +add(docs, linked) str
    }
    class grounding {
        <<module>>
        +verify(final, evidence) ChatAnswer
    }
    class StoredDocument
    class SearchIndex {
        +search(query, k, where) list
    }
    class FinalAnswer {
        <<LLM schema>>
        +answer: str
        +found: bool
        +chunk_id: str
        +page_number: int
        +reference_text: str
    }
    class SourceClaim {
        <<LLM schema>>
        +point: str
        +chunk_id: str
        +reference_text: str
    }
    class ChatAnswer {
        <<API schema>>
        +answer: str
        +page_number: int
        +reference_text: str
        +found: bool
        +tool_calls: list
        +elapsed_seconds: float
    }
    class Source {
        <<API schema>>
        +point: str
        +page_number: int
        +reference_text: str
    }

    ChatService ..> document_tools : creates tools
    ChatService ..> grounding : verifies with
    ChatService ..> FinalAnswer : parses
    ChatService ..> ChatAnswer : returns
    document_tools ..> Evidence : records chunks in
    document_tools ..> StoredDocument : reads
    StoredDocument "1" *-- "1" SearchIndex
    grounding ..> Evidence : checks against
    FinalAnswer "1" *-- "0..*" SourceClaim : sources
    ChatAnswer "1" *-- "0..*" Source : sources
```

**Keeping documents and conversations**

`Repository` is a type alias of the two classes in the code. It is drawn as an interface
because both offer the same methods, and `ChatService` reads history through it.

```mermaid
classDiagram
    direction LR
    class DocumentStore {
        -documents: dict
        +add(data, filename) StoredDocument
        +get(document_id) StoredDocument
        +load_file(document_id) bytes
        +purge_older_than(cutoff) int
        -_build(data, document_id, filename, metadata) StoredDocument
    }
    class StoredDocument {
        +document_id: str
        +filename: str
        +pages: list
        +chunks: list
        +empty_pages: list
        +page_count: int
    }
    class DocumentMetadata {
        +document_type: DocumentType
        +title: str
        +language: str
        +summary: str
        +parties: list
        +key_dates: list
        +governing_law: str
        +case_numbers: list
        +outline: list
        +clause_categories: dict
        +llm_enriched: bool
    }
    class SearchIndex {
        +search(query, k, where) list
    }
    class FileStorage {
        <<abstract>>
        +save(document_id, data)
        +load(document_id) bytes
        +delete(document_id)
    }
    class LocalFileStorage
    class AzureBlobStorage
    class Repository {
        <<interface>>
        +history(conversation_id) BaseChatMessageHistory
        +save_document(record)
        +get_document(document_id) DocumentRecord
        +get_conversation(conversation_id) ConversationRecord
        +touch_conversation(id, client_id, document_id, title)
        +list_conversations(client_id) list
        +delete_conversation(conversation_id)
        +documents_older_than(cutoff) list
        +delete_document(document_id)
    }
    class MemoryRepository
    class PostgresRepository
    class ChatService

    DocumentStore "1" o-- "0..*" StoredDocument : caches
    StoredDocument "1" *-- "1" DocumentMetadata
    StoredDocument "1" *-- "1" SearchIndex
    DocumentStore --> "1" FileStorage
    DocumentStore --> "1" Repository
    ChatService ..> Repository : loads history through
    FileStorage <|-- LocalFileStorage
    FileStorage <|-- AzureBlobStorage
    Repository <|.. MemoryRepository
    Repository <|.. PostgresRepository
```

Pages, chunks and the search index are never stored. They are rebuilt from the PDF after a
restart, which is why [diagram 8](#8-sequence-reopening-a-conversation) needs Blob Storage.

## 6. Class diagram: stored data

Used when `DATABASE_URL` is set. `chat_history` is LangChain's own table and has no
database foreign key; its `session_id` holds the conversation id. A file in Blob Storage is
named `{documents.id}.pdf`.

```mermaid
classDiagram
    direction LR
    class documents {
        <<table>>
        id: varchar[64], PK, sha256
        filename: varchar[255]
        page_count: int
        doc_metadata: json
        created_at: timestamptz
    }
    class conversations {
        <<table>>
        id: varchar[36], PK, browser UUID
        client_id: varchar[100], indexed
        document_id: varchar[64], FK
        title: varchar[200]
        created_at: timestamptz
        updated_at: timestamptz
    }
    class chat_history {
        <<table, LangChain>>
        id: serial, PK
        session_id: uuid
        message: jsonb
        created_at: timestamptz
    }
    class pdf_blob {
        <<blob>>
        name: documents.id + ".pdf"
        content: PDF bytes
    }

    documents "1" -- "0..*" conversations : is discussed in
    conversations "1" -- "0..*" chat_history : session_id
    documents "1" -- "1" pdf_blob : same id
```

## 7. Sequence: asking a question

Requests reach the API through nginx in Docker; it is left out here for space. The chain
runs in a worker thread and passes events through a queue to the streaming response.

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant B as React UI
    participant A as Chat API
    participant S as DocumentStore
    participant C as ChatService
    participant M as NVIDIA NIM
    participant T as Document tools
    participant G as grounding
    participant R as Repository

    U->>B: Types a question
    B->>A: POST /api/chat/stream
    A->>A: Check rate limit
    A->>S: get(document_id)
    S-->>A: StoredDocument
    A->>R: get_conversation(session_id)
    R-->>A: Conversation or none
    alt limit reached, no model, unknown document, or another owner
        A-->>B: 429, 503, 404 or 403
        B-->>U: Shows the error
    else accepted
        A->>C: ask_stream(doc, session_id, question)
        C->>R: Load history
        R-->>C: Last messages, text only
        loop at most 4 model turns, the last forces FinalAnswer
            C->>M: System prompt, history, question, tool results
            alt model calls a document tool
                M-->>C: Tool call
                C-->>B: SSE tool event
                B-->>U: "Searching: ..."
                C->>T: Run the tool
                T->>T: Record returned chunks as evidence
                T-->>C: Chunks as JSON
            else model calls FinalAnswer
                M-->>C: answer, chunk_id, quote, sources
                C-->>B: SSE delta events, if the provider streams arguments
            end
        end
        C->>G: verify(final, evidence)
        G-->>C: ChatAnswer with checked citations
        C->>R: Save question and answer with citations
        C-->>A: Final answer
        A->>R: touch_conversation(...)
        A-->>B: SSE final event
        B-->>U: Answer, page, quote, tool steps
    end

    opt model call fails
        A-->>B: SSE error event
        B-->>U: Shows the error, nothing saved
    end

    opt user clicks Show evidence
        U->>B: Show evidence
        B->>A: GET /api/documents/{id}/file
        A-->>B: Original PDF
        B->>A: POST /api/documents/{id}/highlights
        A-->>B: Boxes in percent of the page
        B-->>U: PDF page with the quote highlighted
    end
```

## 8. Sequence: reopening a conversation

This covers the cloud-backed bonus. After a restart the document is rebuilt without
another metadata call to the LLM. Embeddings are recomputed, because the index only lives
in memory.

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant B as React UI
    participant A as Conversations API
    participant R as Repository
    participant S as DocumentStore
    participant F as Blob Storage
    participant N as NVIDIA NIM
    participant P as PostgreSQL

    B->>A: GET /api/conversations?client_id=
    A->>R: list_conversations(client_id)
    R->>P: Conversations joined with documents
    P-->>R: Rows, newest first
    A-->>B: Summaries for the sidebar
    U->>B: Clicks a conversation
    B->>A: GET /api/conversations/{id}?client_id=
    A->>R: get_conversation(id)
    R-->>A: ConversationRecord
    alt missing, or client_id is not the owner
        A-->>B: 404 Conversation not found
    else owner
        A->>S: get(document_id)
        alt in memory
            S-->>A: StoredDocument
        else not in memory, for example after a restart
            S->>R: get_document(document_id)
            R-->>S: DocumentRecord with saved metadata
            S->>F: load(document_id)
            F-->>S: PDF bytes or none
            alt record and file are both there
                S->>S: Extract, section, chunk again
                S->>N: Embed the chunks
                N-->>S: Vectors
                S-->>A: StoredDocument, no metadata LLM call
            else record or file is gone
                S-->>A: None
                A-->>B: 410 Document no longer available
            end
        end
        A->>R: history(id).messages
        R->>P: Messages for session_id
        P-->>R: Questions and answers with citations
        A-->>B: Document and messages
        B-->>U: Document card and chat, ready for new questions
    end
```

## 9. State machine: a document

```mermaid
stateDiagram-v2
    direction LR
    [*] --> Processing: valid upload
    Processing --> Rejected: unreadable, too many pages, or no text
    Rejected --> [*]: nothing is stored

    Processing --> Active: PDF and record saved

    state "Active (saved, and processed copy in memory)" as Active
    state "Stored (saved, not in memory)" as Stored
    state "Rebuilding" as Rebuilding

    Active --> Active: same file uploaded again
    Active --> Stored: backend restart
    Stored --> Rebuilding: conversation opened or question asked
    Stored --> Processing: same file uploaded again
    Rebuilding --> Active: rebuilt with saved metadata
    Rebuilding --> Stored: PDF file missing (410)

    Active --> Deleted: older than RETENTION_HOURS
    Stored --> Deleted: older than RETENTION_HOURS
    Deleted --> [*]: file, record and its chats removed

    note right of Stored
        Only with PostgreSQL. With the in-memory
        repository a restart loses the document.
    end note
```

## 10. State machine: a question

```mermaid
stateDiagram-v2
    direction TB
    state "Checking request" as Checking
    state "Loading history" as Loading
    state "Calling model" as Calling
    state "Running tools" as Tools
    state "Checking citations" as Verifying
    state "Saving to history" as Saving

    [*] --> Checking: POST /api/chat/stream
    Checking --> Refused: rate limit, no model, unknown document, or wrong owner
    Checking --> Loading: accepted
    Loading --> Calling
    Calling --> Tools: tool calls (turns 1 to 3)
    Tools --> Calling: results returned, tool errors included
    Calling --> Verifying: FinalAnswer called
    Calling --> Verifying: plain text, so found is false
    Calling --> Verifying: turn 4 without FinalAnswer, so answer is empty
    Calling --> Failed: model error or rate limit
    Verifying --> Saving: ChatAnswer built
    Saving --> Answered: final event sent
    Refused --> [*]: HTTP error
    Failed --> [*]: error event, nothing saved
    Answered --> [*]
```

## 11. Data flow (level 1)

Circles are processes, cylinders are data stores and rectangles are external entities. The
level is split into three parts so that it stays readable; store numbers mean the same in
each part.

**Upload and retention**

```mermaid
flowchart LR
    user["User"]
    nim["NVIDIA NIM"]
    timer["Retention timer"]
    p1(("P1<br/>Process<br/>upload"))
    p2(("P2<br/>Extract<br/>metadata"))
    p7(("P7<br/>Purge<br/>expired"))
    d1[("D1 PDF files")]
    d2[("D2 documents")]
    d3[("D3 conversations")]
    d4[("D4 chat_history")]
    d5[("D5 chunks and index<br/>(memory)")]

    user -- "PDF file" --> p1
    p1 -- "document info" --> user
    p1 -- "first pages, outline" --> p2
    p2 -- "prompt" --> nim
    nim -- "fields" --> p2
    p1 -- "chunk texts" --> nim
    nim -- "vectors" --> p1
    p2 -- "record with metadata" --> d2
    p1 -- "PDF bytes" --> d1
    p1 -- "chunks, index" --> d5
    timer -- "every 15 min" --> p7
    d2 -- "expired ids" --> p7
    p7 -- "delete" --> d1 & d2 & d3 & d4 & d5
```

**Answering a question and showing evidence**

```mermaid
flowchart LR
    user["User"]
    nim["NVIDIA NIM"]
    p3(("P3<br/>Answer<br/>question"))
    p4(("P4<br/>Verify<br/>citations"))
    p5(("P5<br/>Locate<br/>quote"))
    d1[("D1 PDF files")]
    d3[("D3 conversations")]
    d4[("D4 chat_history")]
    d5[("D5 chunks and index<br/>(memory)")]

    user -- "question" --> p3
    d4 -- "past messages" --> p3
    d5 -- "chunks" --> p3
    p3 -- "prompt, tool results" --> nim
    nim -- "tool calls, FinalAnswer" --> p3
    p3 -- "conversation title, time" --> d3
    p3 -- "final answer, evidence" --> p4
    p4 -- "verified answer" --> user
    p4 -- "question, answer, citations" --> d4
    user -- "page, quote" --> p5
    d1 -- "PDF bytes" --> p5
    p5 -- "PDF page, highlight boxes" --> user
```

**Saved conversations**

```mermaid
flowchart LR
    user["User"]
    nim["NVIDIA NIM"]
    p6(("P6<br/>Manage<br/>conversations"))
    d1[("D1 PDF files")]
    d2[("D2 documents")]
    d3[("D3 conversations")]
    d4[("D4 chat_history")]
    d5[("D5 chunks and index<br/>(memory)")]

    user -- "client id, selection" --> p6
    p6 -- "list, document, messages" --> user
    d3 -- "conversations" --> p6
    d4 -- "messages" --> p6
    d2 -- "saved metadata" --> p6
    d1 -- "PDF bytes" --> p6
    p6 -- "chunk texts" --> nim
    nim -- "vectors" --> p6
    p6 -- "rebuilt chunks, index" --> d5
```

Document text leaves the system through P1, P2, P3 and P6. This is why the public demo asks
visitors not to upload confidential documents.

## 12. Layered architecture

The system combines three patterns:

- **Client-server:** the React UI talks to the backend only through `/api`.
- **Layered:** routers handle HTTP, services hold the logic, and adapters hold the
  external services.
- **Repository:** the same interfaces hide PostgreSQL or memory, and Blob or a local
  folder, so configuration alone picks the backend.

```mermaid
flowchart TB
    subgraph ui["Presentation: frontend/src"]
        direction LR
        comps["components<br/>UploadPanel · DocumentCard · ChatPanel · ChatMessage<br/>EvidenceViewer · ConversationSidebar · DemoBanner"]
        client["api/client.ts<br/>REST and SSE client"]
        comps --> client
    end

    subgraph api["API: app/api"]
        direction LR
        rdoc["api/documents.py"]
        rchat["api/chat.py"]
        rconv["api/conversations.py"]
    end

    deps["dependencies.py<br/>wires shared services, enforces rate limits"]

    subgraph services["Services: app/services"]
        direction LR
        chat["services/chat.py"]
        tools["document_tools.py"]
        ground["grounding.py"]
        store["document_store.py"]
        pdf["pdf_processing.py<br/>chunk_metadata.py"]
        meta["document_metadata.py"]
        search["search_index.py"]
        quote["quote_location.py"]
    end

    subgraph adapters["Adapters"]
        direction LR
        persist["persistence.py: Memory or PostgreSQL<br/>file_storage.py: Local or Azure Blob"]
        llm["llm.py<br/>chat, embeddings, reranker"]
    end

    subgraph ext["External services"]
        direction LR
        blob[("Azure Blob / Azurite")]
        pg[("PostgreSQL")]
        nim["NVIDIA NIM"]
    end

    client -- "HTTP, SSE" --> api
    api --> deps
    rchat --> chat
    rchat --> store
    rchat -- "persistence.py" --> persist
    rdoc --> store
    rdoc --> quote
    rconv --> store
    rconv -- "persistence.py" --> persist
    chat --> tools
    chat --> ground
    tools --> search
    store --> pdf
    store --> meta
    store --> search
    store --> persist
    deps --> llm
    persist --> blob
    persist --> pg
    llm --> nim
```

## 13. Deployment

This is the `docker-compose.yml` setup. The frontend container is the only entry point the
browser needs, and all published ports bind to `127.0.0.1`.

```mermaid
flowchart LR
    subgraph client["«device» User's computer"]
        browser["«execution environment» Web browser<br/>«artifact» React build<br/>localStorage: client_id"]
    end

    subgraph host["«device» Docker host"]
        subgraph net["«network» compose"]
            subgraph fe["«container» frontend"]
                nginx["nginx<br/>«artifact» static build<br/>proxies /api/"]
            end
            subgraph be["«container» backend"]
                api["uvicorn + FastAPI<br/>processed documents in memory"]
            end
            subgraph dbc["«container» db"]
                pg["PostgreSQL 16"]
            end
            subgraph az["«container» azurite"]
                blob["Azure Blob emulator"]
            end
        end
        v1[("«volume» db_data")]
        v2[("«volume» blob_data")]
    end

    nim["«external» NVIDIA NIM<br/>build.nvidia.com"]

    browser -- "HTTP 8080 → 80" --> nginx
    nginx -- "HTTP 8000<br/>SSE, no buffering" --> api
    api -- "PostgreSQL 5432" --> pg
    api -- "Blob API 10000" --> blob
    api -- "HTTPS" --> nim
    pg --- v1
    blob --- v2
```
