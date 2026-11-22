"""Turn a database address as a hosting provider writes it into one the async driver accepts.

Neon and Vercel hand out `postgresql://user:password@host/db?sslmode=require&channel_binding=require`.
SQLAlchemy needs the driver named (`postgresql+asyncpg://`), and asyncpg takes `ssl=` instead of
`sslmode=` and rejects `channel_binding`. Everything else in the address is kept as it is.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_DRIVER = "postgresql+asyncpg"
_PLAIN_SCHEMES = {"postgres", "postgresql"}
_DROPPED_OPTIONS = {"channel_binding"}


def to_asyncpg_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme in _PLAIN_SCHEMES:
        parts = parts._replace(scheme=_DRIVER)
    if parts.scheme != _DRIVER:
        return url
    options = [
        ("ssl" if name == "sslmode" else name, value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
        if name not in _DROPPED_OPTIONS
    ]
    return urlunsplit(parts._replace(query=urlencode(options)))
