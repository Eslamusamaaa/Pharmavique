"""Scratch: pick the next brands to search by hand (retail dosage forms first, each brand once)."""

import json
import sys
from pathlib import Path

from pharmavique.bootstrap.images import load_product_refs
from pharmavique.media.domain.matching import build_queries
from pharmavique.media.domain.placeholders import form_group
from pharmavique.shared_kernel.names import core_name
from pharmavique.shared_kernel.text import normalize_text

size = int(sys.argv[1]) if len(sys.argv) > 1 else 15
state_path = Path("data/media/manual/state.json")
state_path.parent.mkdir(parents=True, exist_ok=True)
state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"searched": []}
searched = set(state["searched"])

has_real = set()
for line in open("data/media/images.jsonl", encoding="utf-8"):
    if line.strip():
        has_real.add(json.loads(line)["register_number"])
forms = {}
for line in open("data/media/products.jsonl", encoding="utf-8"):
    row = json.loads(line)
    forms[row["register_number"]] = row.get("dosage_form_en")

retail = {"tablet", "capsule", "liquid", "topical", "drops"}
batch: list[str] = []
for ref in load_product_refs(Path("data/media/products.jsonl")):
    if ref.register_number in has_real or form_group(forms.get(ref.register_number)) not in retail:
        continue
    brand = normalize_text(core_name(ref.trade_name_en))
    if not brand or brand in searched:
        continue
    searched.add(brand)
    batch.append(build_queries(ref)[0])
    if len(batch) == size:
        break

state["searched"] = sorted(searched)
state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
Path("data/media/manual/batch.json").write_text(json.dumps(batch, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(searched)} brands marked as searched so far")
for query in batch:
    print(query)
