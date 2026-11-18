# ADR-007: LangGraph and LangChain only inside the assistant's infrastructure

| | |
|---|---|
| Status | **Accepted** (owner, 2026-11-18) |
| Date | 2026-11-18 |
| Related | ADR-005, [AI_ARCHITECTURE.md](../AI_ARCHITECTURE.md) sections 2 and 7, [PHASE_2_PLAN.md](../PHASE_2_PLAN.md) |

## Context

The owner wants LangGraph and LangChain for the agentic assistant, and onion architecture with DDD.
These frameworks change quickly and bring their own message and tool types.

## Decision

- The assistant's **application layer** defines what an answer is (text, citations, level, refusal),
  the tools (typed, read-only, over other contexts' contracts), the guardrails (step, time and cost
  limits; citation required; no dosing, no "stop" or "switch"; retrieved text is data, never
  instructions) and an `AgentRunner` port.
- **The LangGraph graph is one adapter** in `assistant/infrastructure` that implements `AgentRunner`.
  LangChain is used there for model and tool bindings. Our tools are wrapped into LangChain tools at
  that edge only.
- The import contracts forbid `langchain`, `langchain_core`, `langgraph`, `openai`, `groq` and
  `sentence_transformers` in every `domain` and `application` package, next to the frameworks already
  forbidden. `lint-imports` enforces it in CI.
- Guardrails are checked in our code after the graph returns (citations present and pointing at
  records the tools returned), not only in prompts.

## Consequences

- Replacing or upgrading LangGraph touches one adapter and its tests.
- A fake `AgentRunner` lets the API and the app be built before any model key exists.
