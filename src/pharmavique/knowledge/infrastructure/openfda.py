"""Drug-label interaction text from openFDA (the public label API of the US FDA).

openFDA serves the structured drug labels published on DailyMed. We take only the "drug
interactions" section of one label per ingredient, with the label's DailyMed page as the source,
so the assistant can quote it with a citation. The text is a US label: it says what that label
says, not what is registered in Saudi Arabia.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

LABEL_URL = "https://api.fda.gov/drug/label.json"
DAILYMED_PAGE = "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid="


@dataclass(frozen=True, slots=True)
class LabelInteractions:
    generic_name: str
    set_id: str
    effective_time: str | None  # ISO date
    text: str
    source_ref: str


def _iso(date: str | None) -> str | None:
    if date and len(date) == 8 and date.isdigit():
        return f"{date[:4]}-{date[4:6]}-{date[6:]}"
    return None


def _is_the_wanted_single_drug(generic_name: str, wanted: str) -> bool:
    """A one-ingredient label of the wanted drug: not a combination, same first word."""
    lowered = generic_name.lower()
    if any(mark in lowered for mark in (" and ", ",", "/", " with ", "+")):
        return False
    first = lowered.split()[:1]
    return first == wanted.lower().split()[:1]


def parse_label(payload: dict[str, Any], wanted: str | None = None) -> LabelInteractions | None:
    """The first label of an openFDA answer that has a drug-interactions section.

    With `wanted`, only a one-ingredient label of that drug counts (never a combination product).
    """
    for result in payload.get("results") or []:
        sections = [s for s in result.get("drug_interactions") or [] if str(s).strip()]
        set_id = result.get("set_id")
        if not sections or not set_id:
            continue
        names = (result.get("openfda") or {}).get("generic_name") or [""]
        if wanted is not None and not _is_the_wanted_single_drug(str(names[0]), wanted):
            continue
        return LabelInteractions(
            generic_name=str(names[0]),
            set_id=str(set_id),
            effective_time=_iso(result.get("effective_time")),
            text="\n\n".join(str(s).strip() for s in sections),
            source_ref=f"{DAILYMED_PAGE}{set_id}",
        )
    return None


class OpenFdaLabels:
    """One request at a time, a pause between requests, a plain user agent."""

    def __init__(self, client: httpx.AsyncClient, delay: float = 0.6) -> None:
        self._client = client
        self._delay = delay

    async def interactions_for(self, generic_name: str) -> LabelInteractions | None:
        words = " AND ".join(generic_name.split())
        response = await self._client.get(
            LABEL_URL,
            params={
                "search": f"openfda.generic_name:({words}) AND _exists_:drug_interactions",
                "limit": 25,
            },
        )
        await asyncio.sleep(self._delay)
        if response.status_code == 404:
            return None  # openFDA answers 404 when nothing matches
        response.raise_for_status()
        return parse_label(response.json(), wanted=generic_name)
