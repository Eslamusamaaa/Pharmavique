"""Account commands run on the server.

`pharmavique create-operator`: make an operator account (never through the public sign-up). The
password is read from the terminal without echo, or from the environment variable
`PHARMAVIQUE_OPERATOR_PASSWORD` for scripts. It is never taken from the command line, where it
would stay in the shell history.

`pharmavique verify-account --email E [--reject] [--note N]`: verify or reject a pharmacist or
company account and email the person (ADR-020); the operator screen does the same.
"""

import argparse
import getpass
import os
import sys
from typing import Any

from pharmavique.bootstrap.identity_wiring import build_email_sender, build_identity
from pharmavique.bootstrap.settings import get_settings
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.identity.domain.user import AccountNotFound, EmailTaken
from pharmavique.identity.infrastructure.tokens import JwtAccessTokens
from pharmavique.shared_kernel.email import EmailError
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

    review = commands.add_parser(
        "verify-account",
        help="verify (or with --reject, reject) a pharmacist or company account; emails the person",
    )
    review.add_argument("--email", required=True)
    review.add_argument("--reject", action="store_true", help="reject instead of verifying")
    review.add_argument("--note", default=None, help="the reason, shown to the person")


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


async def verify_account(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.database_url is None or settings.jwt_secret is None:
        print("set PHARMAVIQUE_DATABASE_URL and PHARMAVIQUE_JWT_SECRET first", file=sys.stderr)
        return EXIT_NO_DATABASE
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        factory = create_session_factory(engine)
        service = build_identity(
            settings, factory, JwtAccessTokens(settings.jwt_secret.get_secret_value())
        )
        try:
            view, message = await service.review_role_by_email(
                args.email, approve=not args.reject, note=args.note
            )
        except AccountNotFound:
            print("no account has this email", file=sys.stderr)
            return EXIT_REJECTED
        except InvariantViolation as error:
            print(str(error), file=sys.stderr)
            return EXIT_REJECTED
    finally:
        await engine.dispose()
    print(f"{view.email}: {view.role_review.value}")
    try:
        await build_email_sender(settings).send(message)
    except (EmailError, ValueError) as error:
        print(f"the decision is saved, but the email was not sent: {error}", file=sys.stderr)
    return EXIT_OK
