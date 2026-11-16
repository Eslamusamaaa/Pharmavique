from pharmavique.foundation.http.robots import RobotsPolicy

ROBOTS = """
# comment
User-agent: *
Allow: /core/*.css$
Disallow: /core/
Disallow: /admin/
Disallow: /search?
Disallow: /*/media/oembed
Disallow:

User-agent: BadBot
Disallow: /
"""

UA = "pharmavique-dev (contact: owner)"


def policy(text: str = ROBOTS, ua: str = UA) -> RobotsPolicy:
    return RobotsPolicy.from_text(text, ua)


def test_paths_with_no_matching_rule_are_allowed() -> None:
    assert policy().allows("https://example.org/en/drugs-list?page=3")
    assert policy().allows("https://example.org/en/details_data?nid=1&id=2&page=0")


def test_disallowed_prefixes_are_blocked() -> None:
    assert not policy().allows("https://example.org/admin/config")
    assert not policy().allows("https://example.org/core/misc/app.js")


def test_query_is_part_of_the_match() -> None:
    assert not policy().allows("https://example.org/search?keys=x")
    assert policy().allows("https://example.org/search")


def test_wildcards_match_across_segments() -> None:
    assert not policy().allows("https://example.org/en/media/oembed")


def test_longer_allow_rule_beats_shorter_disallow() -> None:
    assert policy().allows("https://example.org/core/theme/style.css")


def test_dollar_anchors_the_end_of_the_url() -> None:
    assert not policy().allows("https://example.org/core/theme/style.css.map")


def test_specific_user_agent_group_replaces_the_wildcard_group() -> None:
    assert not policy(ua="Mozilla BadBot/1.0").allows("https://example.org/en/drugs-list")


def test_empty_or_missing_robots_allows_everything() -> None:
    assert policy("").allows("https://example.org/anything")
    assert policy("User-agent: *\nDisallow:\n").allows("https://example.org/anything")


def test_tie_between_allow_and_disallow_goes_to_allow() -> None:
    text = "User-agent: *\nDisallow: /same\nAllow: /same\n"

    assert policy(text).allows("https://example.org/same")
