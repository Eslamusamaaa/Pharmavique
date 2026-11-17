"""Errors shared by the SFDA crawlers."""


class CrawlError(Exception):
    """The crawl cannot continue."""


class SourceBlocked(CrawlError):
    """robots.txt forbids the URL or the site answered 401/403/429. Stop; do not work around it."""


class FetchFailed(CrawlError):
    """One URL could not be fetched or parsed after the allowed retries."""


class NotFound(FetchFailed):
    """The site answered 404 for this URL."""


class TooManyFailures(CrawlError):
    """Many pages in a row failed, which usually means the site is blocking or has changed."""
