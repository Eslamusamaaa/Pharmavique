"""Turn a spoken request into a search query: the drug name, not the whole sentence."""

from dataclasses import dataclass

from pharmavique.voice.application.ports import DrugNameExtractor
from pharmavique.voice.domain.names import clean_model_name, strip_filler

MAX_SPOKEN = 500


@dataclass(frozen=True, slots=True)
class SpokenQuery:
    query: str  # what to search for
    name: str | None  # the drug name the model found; None when it fell back to the rules
    understood: bool  # True when the model named the medicine


class ExtractDrugName:
    def __init__(self, extractor: DrugNameExtractor | None) -> None:
        self._extractor = extractor

    async def run(self, text: str) -> SpokenQuery:
        text = " ".join(text.split())
        if not text or len(text) > MAX_SPOKEN:
            raise ValueError(f"the spoken text must be 1 to {MAX_SPOKEN} characters")
        name = await self._ask(text)
        if name is not None:
            return SpokenQuery(query=name, name=name, understood=True)
        return SpokenQuery(query=strip_filler(text), name=None, understood=False)

    async def _ask(self, text: str) -> str | None:
        if self._extractor is None:
            return None
        try:
            answer = await self._extractor.extract(text)
        except Exception:
            return None  # a busy or failing model never blocks a search
        return clean_model_name(answer) if answer else None
