# ADR-008: a separate `interactions` context for drug-interaction checks

Status: accepted, 2026-11-21 (owner asked for interaction checks for pharmacist, patient and assistant).

## Context

The app needs to say "these two medicines have a recorded interaction", "these two contain the same
ingredient" and, later, drug-food and drug-condition notes. The data comes from outside sources
(first: DDInter 2.0, 234,757 drug pairs with a severity rating), not from the SFDA registry.

## Decision

- A new context `interactions` with its own schema `interactions` (table `pair`), its own migration
  branch and the usual layers. It owns nothing of the catalog.
- Products are matched to the source by **active ingredient name**, never by trade name. The
  registry's ingredient lists are already split per ingredient. `domain/names.py` turns a registry
  name into the keys to look up: as written, without brackets, without salt or ester words
  (`AMLODIPINE BESILATE` gives `amlodipine`), and under the spelling the sources use
  (`PARACETAMOL` gives `acetaminophen`). The registry's own name is never changed.
- The check lives in `application/check.py` behind a store port. The catalog is read in the
  composition root (`bootstrap/api_interactions.py`), not inside the context.
- A finding carries its source and the severity **as the source rates it**. Duplicates (same base
  ingredient in two products) come from our own registry data and carry no source.
- Ingredients the source has no record of are returned as `unmatched`. The report is never
  complete: `complete` is always false, so "nothing found" is never "safe".
- No dosing, no "stop" or "switch": the API states what a source records and the pharmacist or
  doctor decides.
- Source rows are stored with provenance and `trust = unofficial_unverified`.

## Consequences

- More sources (drug-food and drug-disease from DDInter, label text for the assistant) plug in as
  further loaders into the same schema or as chunks in `knowledge`.
- Coverage is bounded by name matching: on 2026-11-21, 921 of 1,673 distinct registry ingredient
  names (75.6% of ingredient occurrences) were known to DDInter; the rest are mostly nutrients,
  infusions, biologics and newer molecules.
- The pair table stores names in byte order (`COLLATE "C"`) so the database and Python agree on
  which name comes first.
