# Model selection

**Decision (2026-10-31, revised the same day after live tests):**

| Role | Model | Endpoint |
|---|---|---|
| Chat, tool calling, structured output | `mistralai/mistral-large-4-1t-a52b` with `reasoning_effort=low` | NVIDIA NIM free endpoint (build.nvidia.com) |
| Embeddings (semantic search over chunks) | `nvidia/nemotron-3-embed-1b` | NVIDIA NIM free endpoint |
| Reranking search results | `nvidia/llama-nemotron-rerank-vl-1b-v2` | NVIDIA NIM free endpoint |
| First alternative for chat | `google/gemma-4-31b-it` | same endpoint, same key |

Both are called through LangChain (`langchain-nvidia-ai-endpoints`). Switching models is
a change in `.env` (`NVIDIA_MODEL`, `LLM_REASONING_EFFORT`), not in code.

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
6. **Available and predictable** behaviour, more than top benchmark scores. The case says
   the focus is system design, not model performance.

## Candidates (free endpoints on build.nvidia.com, filtered on 2026-10-31)

| Model | Tool calling | Structured output | Context | Notes |
|---|---|---|---|---|
| **`mistralai/mistral-large-4-1t-a52b`** | yes | strict JSON schema | 1M | ~1T MoE / 49B active, 160+ languages, legal listed as a use case, reasoning effort low/medium/high |
| `google/gemma-4-31b-it` | yes | via tools | 256K | Dense 30.7B, 140+ languages, Apache 2.0, thinking off by default |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | yes | yes | — | 30B MoE with ~3B active; model card lists only 6 languages (no Turkish) |
| `nvidia/nemotron-3.5-super-vl-120b-a12b` | yes | yes | — | early access |
| `z-ai/glm-5-3-flash`, `deepseek-v4.1-flash`, `Step 5 Preview` | yes | — | large | very large MoE models on a shared free queue |
| `openai/gpt-oss-20b` | yes | — | — | reasoning-focused, timed out in earlier tests |

Google Gemini (the initial choice in this repo) was dropped: its free tier is capped at
a few dozen requests per day, which a single test session or a public demo exceeds.

## How the decision was made

**First pick: Gemma 4 31B, based on earlier measurements.** In a previous project of mine
I evaluated free NIM models on a Turkish tool-routing task (56 questions, cache disabled,
plus a paraphrased variant set). Gemma 4 31B picked the correct tool in 55/56 cases and
reached 92.9% end-to-end accuracy on both sets, while Nemotron 3.5 Lightning, GLM 5.3
Flash, Mistral Nemotron and gpt-oss-20b failed the pre-screen (wrong tools, timeouts,
HTTP 500). Mistral Large 4 had been on the endpoint for two days, so it was ranked second.

**Live test on 2026-10-31 reversed the order:**

| Test (same key, same day) | `gemma-4-31b-it` | `mistral-large-4-1t-a52b` (effort low) |
|---|---|---|
| Trivial prompt ("17 × 23") | 7 of 7 attempts timed out (45–120 s) | 2.5–5.3 s, correct |
| Metadata extraction on a 3-page PDF (forced tool call) | not reachable | 10.7–14.5 s, valid schema, correct title/language/summary/parties |
| `nemotron-3.5-lightning` (control) | — | 0.6 s (endpoint itself was healthy) |

A model that does not answer cannot serve a chat UI or a public demo, so Mistral Large 4
became the default. Its card also matches the task well: native function calling, strict
JSON schema, 1M context, 160+ languages, and law listed among its use cases.
`reasoning_effort=low` keeps answers fast; the default (`high`) spent the whole token
budget on reasoning in our test and returned no tool call.

Gemma 4 31B stays the first alternative. Switching back is `NVIDIA_MODEL=google/gemma-4-31b-it`
and `LLM_REASONING_EFFORT=` (empty).

## Why nemotron-3-embed-1b for embeddings

- **Free endpoint on the same platform and API key**, so one key runs the whole system.
- Text-only and small (1.1B), 32K max sequence length, 2048-dim vectors.
- Highest retrieval scores among NVIDIA's small embedders on the card (RTEB 72.4 vs 60.5
  for the previous 1B generation).
- The newer `nemotron-3.5-embed-1b` is multimodal (page images) and ten days old. We only
  embed text, so the text-only model is the simpler choice.
- **Live check:** a Turkish query ("Sözleşme nasıl feshedilir?") ranked the Turkish
  termination clause highest among three test passages; one request took 0.9 s.
- **Caveat:** Turkish is not in the card's list of 34 evaluated languages. The tool layer
  therefore does not rely on embeddings alone: `find_clauses` and `get_document_info` use
  rule-based metadata (`backend/app/services/chunk_metadata.py`), and `get_page` reads
  pages directly.

## Findings from the live tests that changed the code

| Finding | Change |
|---|---|
| `ChatNVIDIA.with_structured_output` sends an NVIDIA-specific `guided_json` field; the hosted endpoint rejects it with HTTP 400 | `app/llm.py: structured_output()` sends the schema as a **forced tool call** and parses it with `PydanticToolsParser`. Works with any model that supports tool calling |
| Reasoning tokens count against `max_completion_tokens`; with the library default the answer was cut off (`finish_reason=length`) | `LLM_MAX_TOKENS=4096` and `LLM_REASONING_EFFORT=low` are set explicitly |
| A model can answer without calling the schema tool | The parser returns `None`; metadata extraction then falls back to rule-based fields instead of failing the upload |

## Known risks and how they are handled

| Risk | Mitigation |
|---|---|
| Free endpoint latency spikes or outages (seen today for Gemma) | Timeout; model is a `.env` setting; rule-based fallback for metadata; streaming (later iteration) so the user sees progress |
| Model returns a wrong page number or quote | The backend verifies `chunk_id`, takes `page_number` from chunk metadata and checks `reference_text` against the chunk text |
| Free tier rate limits on the public demo | Per-IP rate limit and upload limits on the backend |
| Mistral Large 4 is new on the endpoint | Gemma 4 31B is a tested alternative behind the same code path |
| Turkish not explicitly listed for the embedding model | Rule-based metadata and keyword rules handle Turkish (Turkish-aware lowercasing), verified with Turkish test cases |
| Vendor recommends `temperature=1.0` | We use `0.0` for repeatable extraction and tool choice |
