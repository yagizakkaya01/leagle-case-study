# Model selection

**Decision (2026-10-31):**

| Role | Model | Endpoint |
|---|---|---|
| Chat, tool calling, structured output | `google/gemma-4-31b-it` | NVIDIA NIM free endpoint (build.nvidia.com) |
| Embeddings (semantic search over chunks) | `nvidia/nemotron-3-embed-1b` | NVIDIA NIM free endpoint |

Both are called through LangChain (`langchain-nvidia-ai-endpoints`), so switching to
another model is a change in `.env`, not in code.

---

## What the case needs from a model

1. **Tool calling.** The chat layer lets the model pick tools (`search_document`,
   `get_page`, `find_clauses`, `get_document_info`) instead of guessing from memory.
2. **Structured output.** Every answer must come back as `answer`, `page_number`,
   `reference_text`, and document metadata is extracted into a fixed schema.
3. **Long enough context** for the conversation history plus retrieved chunks, and for
   reading the first pages of a document at upload time.
4. **Multilingual.** Legal documents may be English or Turkish.
5. **A free endpoint** that a reviewer, or a public demo, can use without a paid plan.
6. **Stable and predictable** behaviour, more than top benchmark scores. The case says
   the focus is system design, not model performance.

## Candidates (free endpoints on build.nvidia.com, filtered on 2026-10-31)

| Model | Tool calling | Structured output | Context | Notes |
|---|---|---|---|---|
| **`google/gemma-4-31b-it`** | yes | yes (JSON schema via tools) | 256K | Dense 30.7B, 140+ languages, Apache 2.0, thinking off by default, released 04/2026 |
| `mistralai/mistral-large-4-1t-a52b` | yes | strict JSON schema | 1M | ~1T MoE / 49B active, 160+ languages, legal listed as a use case; **released 2 days ago**, reasoning effort defaults to *high* |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | yes | yes | — | 30B MoE with ~3B active; model card lists only 6 languages (no Turkish) |
| `nvidia/nemotron-3.5-super-vl-120b-a12b` | yes | yes | — | early access |
| `z-ai/glm-5-3-flash`, `deepseek-v4.1-flash`, `Step 5 Preview` | yes | — | large | very large MoE models on a shared free queue |
| `openai/gpt-oss-20b` | yes | — | — | reasoning-focused, timed out in earlier tests |

Google Gemini (the initial choice in this repo) was dropped: its free tier is capped at
a few dozen requests per day, which a single test session or a public demo exceeds.

## Why Gemma 4 31B

- **Measured, not assumed.** In a previous project of mine I evaluated free NIM models
  on a Turkish tool-routing task (56 questions, cache disabled, paraphrased variant set).
  Gemma 4 31B picked the correct tool in **55/56** cases and reached **92.9%**
  end-to-end accuracy on both the original and the paraphrased set. Nemotron 3.5
  Lightning, GLM 5.3 Flash, Mistral Nemotron and gpt-oss-20b either picked wrong tools,
  timed out or returned HTTP 500 in the same pre-screen.
- **Dense model.** All 30.7B parameters are active per token, versus ~3B for the
  Lightning MoE. In that evaluation, the small active size showed up as tool choices that
  ignored explicit routing rules.
- **Fits every requirement:** native function calling, 256K context, 140+ languages,
  Apache 2.0 licence.
- **Thinking is off by default**, which keeps latency and token use low for a chat UI.
- **Mature on the platform** (released 04/2026, millions of calls), so behaviour and
  quirks are known.

### Why not Mistral Large 4 (yet)

On paper it is the strongest fit (strict JSON schema, 1M context, legal use cases). It
was published on the endpoint two days before this decision, its default reasoning
effort is *high* (slower, more tokens), and a ~1T-parameter model on a shared free queue
is likely to be the slowest option. It stays the first alternative: set
`NVIDIA_MODEL=mistralai/mistral-large-4-1t-a52b` to try it.

## Why nemotron-3-embed-1b for embeddings

- **Free endpoint on the same platform and API key**, so one key runs the whole system.
- Text-only and small (1.1B), 32K max sequence length, 2048-dim vectors (can be sliced to
  1024/512).
- Highest retrieval scores among NVIDIA's small embedders on the card (RTEB 72.4 vs 60.5
  for the previous 1B generation).
- Released 07/2026; the newer `nemotron-3.5-embed-1b` is multimodal (page images) and ten
  days old. We only embed text, so the older, text-only model is the simpler choice.
- **Caveat:** Turkish is not in the model card's list of 34 evaluated languages. The tool
  layer therefore does not rely on embeddings alone: `find_clauses` and
  `get_document_info` use rule-based metadata (see `backend/app/services/chunk_metadata.py`),
  and `get_page` reads pages directly.

## Known risks and how they are handled

| Risk | Mitigation |
|---|---|
| Free endpoint latency spikes (queueing, observed 1–30 s on the same request) | Timeout + `max_retries=2`; streaming (later iteration) so the user sees progress |
| Model returns a wrong page number or quote | The backend verifies `chunk_id`, takes `page_number` from chunk metadata and checks `reference_text` against the chunk text |
| Free tier rate limits on the public demo | Per-IP rate limit and upload limits on the backend |
| Turkish not explicitly listed for either model | Rule-based metadata and keyword rules handle Turkish (Turkish-aware lowercasing); verified with Turkish test cases |
| `langchain-nvidia-ai-endpoints` 1.5 warns that `google/gemma-4-31b-it` "is not known to support structured output" (its static model table predates the model) | The package sends a JSON schema (`response_format` / `guided_json`), which the vLLM-served endpoint enforces independently of the table. To be confirmed with a live call; if it fails, the same schema is sent as a forced tool call |
| Gemma 4 recommends `temperature=1.0` | We use `0.0` for repeatable extraction and tool choice, as in the earlier evaluation |
