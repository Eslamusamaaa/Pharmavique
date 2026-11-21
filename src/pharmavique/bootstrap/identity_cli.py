"""`pharmavique create-operator`: make an operator account (never through the public sign-up).

The password is read from the terminal without echo, or from the environment variable
`PHARMAVIQUE_OPERATOR_PASSWORD` for scripts. It is never taken from the command line, where it
would stay in the shell history.
"""

import argparse
import getpass
import os
import sys
from typing import Any

from pharmavique.bootstrap.identity_wiring import build_identity
from pharmavique.bootstrap.settings import get_settings
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.identity.domain.user import EmailTaken
from pharmavique.identity.infrastructure.tokens import JwtAccessTokens
from pharmavique.shared_kernel.errors import InvariantViolation

EXIT_OK = 0
EXIT_NO_DATABASE = 4
EXIT_REJECTED = 5
PASSWORD_VARIABLE = "PHARMAVIQUE_OPERATOR_PASSWORD"  # noqa: S105 (a variable name, not a password)


def add_arguments(commands: Any) -> None:
    operator = commands.add_parser(
        "create-operator",
        help="create an operator account (password from a prompt or "
        f"{PASSWORD_VARIABLE}, never from the command line)",
    )
    operator.add_argument("--email", required=True)


async def create_operator(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.database_url is None or settings.jwt_secret is None:
        print("set PHARMAVIQUE_DATABASE_URL and PHARMAVIQUE_JWT_SECRET first", file=sys.stderr)
        return EXIT_NO_DATABASE
    password = os.environ.get(PASSWORD_VARIABLE) or getpass.getpass("Password: ")
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        factory = create_session_factory(engine)
        service = build_identity(
            settings, factory, JwtAccessTokens(settings.jwt_secret.get_secret_value())
        )
        try:
            view = await service.create_operator(args.email, password)
        except InvariantViolation as error:
            print(str(error), file=sys.stderr)
            return EXIT_REJECTED
        except EmailTaken:
            print("this email already has an account", file=sys.stderr)
            return EXIT_REJECTED
    finally:
        await engine.dispose()
    print(f"operator created: {view.email}")
    return EXIT_OK
