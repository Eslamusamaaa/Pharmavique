"""A pytest plugin (loaded with `-p pv_isolation`): tests do not depend on the developer's `.env`.

A set variable beats the `.env` file, so these empty ones switch off what the real file may enable
and a test never meant to see: the website the API serves at `/` would answer addresses that the
API tests expect to be unknown.
"""

import os

os.environ["PHARMAVIQUE_WEB_DIR"] = ""
