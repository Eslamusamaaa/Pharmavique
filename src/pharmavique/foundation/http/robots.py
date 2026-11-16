"""A small robots.txt matcher with `*` and `$` support (the stdlib parser has neither).

Semantics follow the common convention: the most specific user-agent group wins, the longest
matching rule wins, and on a tie `Allow` beats `Disallow`. No rule matching means allowed.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlparse

_Rule = tuple[bool, str]  # (allow, pattern)


def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile(regex + ("$" if anchored else ""))


@dataclass(frozen=True, slots=True)
class RobotsPolicy:
    rules: tuple[_Rule, ...]

    @classmethod
    def from_text(cls, text: str, user_agent: str) -> "RobotsPolicy":
        groups: list[tuple[list[str], list[_Rule]]] = []
        previous_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            field, _, value = line.partition(":")
            field = field.strip().lower()
            value = value.strip()
            if field == "user-agent":
                if not previous_was_agent:
                    groups.append(([], []))
                groups[-1][0].append(value.lower())
                previous_was_agent = True
                continue
            previous_was_agent = False
            if field in ("allow", "disallow") and groups and value:
                groups[-1][1].append((field == "allow", value))

        ua = user_agent.lower()
        specific = [g for g in groups if any(a != "*" and a in ua for a in g[0])]
        chosen = specific or [g for g in groups if "*" in g[0]]
        return cls(tuple(rule for _, rules in chosen for rule in rules))

    def allows(self, url: str) -> bool:
        parsed = urlparse(url)
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query

        best: tuple[int, bool] | None = None  # (pattern length, allow)
        for allow, pattern in self.rules:
            if _compile(pattern).match(target) is None:
                continue
            candidate = (len(pattern), allow)
            if best is None or candidate[0] > best[0] or (candidate[0] == best[0] and allow):
                best = candidate
        return True if best is None else best[1]
