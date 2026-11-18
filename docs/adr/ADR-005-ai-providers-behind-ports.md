# ADR-005: AI providers (LLM, vision, embeddings, speech, web search) behind ports

| | |
|---|---|
| Status | **Accepted** (owner, 2026-11-18) |
| Date | 2026-11-18 |
| Related | [PHASE_2_PLAN.md](../PHASE_2_PLAN.md), [AI_ARCHITECTURE.md](../AI_ARCHITECTURE.md), ADR-004, OPEN_QUESTIONS Q-9, Q-31 |

## Context

The owner wants an LLM, a vision-language model, an embedding model, speech to text, text to speech
and a web search tool. Candidate providers (OpenRouter, Groq) and models came from the owner's notes
and are **not verified** here; keys come later. Provider offers, limits and model names change often,
and free tiers have low daily limits.

## Decision

- Each capability is an **application-layer port** owned by the context that uses it: `LanguageModel`
  and `WebSearch` (assistant), `VisionReader` (recognition), `Embedder` (knowledge and search),
  `SpeechToText` and `TextToSpeech` (voice). Ports speak in our own types (text, lines, vectors,
  citations), never in a provider's.
- Adapters live in `infrastructure`. Provider, base URL, model id and key come from environment
  variables (`.env.example` holds placeholders only). Changing a model is a configuration change;
  changing a provider is one new adapter.
- Every port has a **fake adapter** used by tests and by local runs without keys.
- Calls are throttled, time-limited and retried with a circuit breaker; cost and tokens are recorded
  per tenant (ADR-004). Prompts and outputs that contain health data are never written to logs.
- The owner allowed hosted providers, free tiers included, for photos, voice and medication lists
  (Q-9, 2026-11-18). Uploads are still deleted after processing.
- No local model runtime is installed (owner, Q-31): embeddings also come from an API.

## Consequences

- The domain and application layers stay testable without any provider or key.
- Model claims (context size, JSON mode, vision, limits) are checked against the provider's
  documentation when each adapter is written.
- Free-tier limits may stop features under load; the circuit breaker answers "try again later" or
  falls back to plain search instead of failing silently.
