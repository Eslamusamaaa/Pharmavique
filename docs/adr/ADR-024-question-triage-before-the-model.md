# ADR-024: sorting each assistant question before the model sees it

Status: accepted, 2026-11-26 (audit 2026-11, Part C; owner's answers in `docs/AUDIT_2026-11_PLAN.md`
§3). Builds on ADR-007 (LangGraph in infrastructure).

## Context

One LangGraph agent decided everything from the system prompt. Real conversations went wrong in the
same way: "I have a migraine, what can help?" got Sumatriptan and Rizatriptan at once, with nothing
asked and no warning; a severe headache was not checked for urgent signs; "can I take Panadol with
Sumatriptan" could be answered with "no interaction, take them together". The prompt allowed
"ingredients generally used for these symptoms" with no step before it, and the only code-level
urgent check was the emergency regex (overdose, breathing, swelling, fainting, seizure, self-harm),
with no headache red flags.

## Decision

- **Deterministic triage in the domain** (`assistant/domain/triage.py`, pure, no framework): each
  question gets one kind: `red_flag`, `interaction`, `drug_safety`, `symptom_treatment`,
  `drug_info` or `other`, plus the symptoms it names and the dialect to answer in. A follow-up that
  is only an answer ("not pregnant, no other medicines") keeps the kind of the question it answers.
  The model never decides what kind of question it got.
- **Red flags are answered without a model.** A sudden worst headache, weakness or numbness,
  trouble speaking, vision change, fever with a stiff neck, a head injury or chest pain, when the
  person reports it (not when they ask about it), gets a fixed urgent-care reply (outcome
  `red_flag`, `urgent`). It runs after the emergency check and before the injection check.
- **Each other kind gives the model a short instruction** (`guidance`, a new `AgentRunner.run`
  argument, appended to the system prompt): information questions are answered directly with no
  questionnaire; treatment requests get the categories, may name registered products (owner,
  2026-11-26: prescription-only ones included, said to need a prescription), and ask what is
  missing (severity, other symptoms, age, pregnancy, chronic illnesses, other medicines, allergies);
  interaction questions must call `check_interactions` and say one of documented / none recorded /
  not covered; safety questions must call `contraindications` and never reassure.
- **Rules after the model, in code:** for interaction, safety and treatment questions, a sentence
  that clears a medicine or a combination ("safe", "no interaction", "no risk") is removed unless it
  only reports what a source records or says the opposite, and a note says that no record is not a
  clearance. A treatment request always ends with the "consult a doctor or pharmacist before any
  medicine" warning, and for a headache with the urgent-signs note, whatever the model wrote. The
  earlier guards (no dose, no stop/switch, numbers and register numbers from tools) still run first.
- **Dialect follows the question** (owner, 2026-11-26): Egyptian Arabic for Egyptian, English for
  English, light Saudi otherwise. Fixed replies and notes stay Saudi.
- **Feature flag** `PHARMAVIQUE_FEATURE_TRIAGE` (on by default): off restores the earlier behaviour.

## Consequences

- The kind of each question is testable without a model; the six real conversations are regression
  tests (`tests/unit/assistant/test_medical_regressions.py`) over a fake model that gives the
  observed bad answers. They check what the code guarantees, not what a real model writes; a live
  evaluation over real models is still to be built (plan item 5, live part).
- Keyword rules miss phrasings and can misfire (for example "take X with food" reads as an
  interaction question). A miss falls back to the earlier behaviour (all guards still run); the
  red-flag rules lean to sending people to urgent care.
- The clearance filter can remove a correct sentence such as "safe to store at room temperature" in
  those three kinds of question; that costs a sentence, never a wrong reassurance.
- Contraindication and interaction *data* are unchanged: their gaps (no Saudi label sections,
  DDInter coverage) remain and are planned in the audit's later batches.
