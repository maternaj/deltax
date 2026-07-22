"""Settler DB env resolution tests."""

from deltax.settle.db import _settler_env


def test_settler_env_from_decomposed_vars() -> None:
    env = _settler_env(
        {
            "DELTAX_DB_HOST": "writer-host",
            "DELTAX_DB_USER": "deltax_writer",
            "DELTAX_SETTLE_DB_HOST": "settler-host",
            "DELTAX_SETTLE_DB_PORT": "5432",
            "DELTAX_SETTLE_DB_NAME": "alex",
            "DELTAX_SETTLE_DB_USER": "deltax_settler",
            "DELTAX_SETTLE_DB_PASSWORD": "secret",
            "DELTAX_SETTLE_DB_SSLMODE": "prefer",
        }
    )
    assert env["DELTAX_DATABASE_URL"].startswith("postgresql://deltax_settler:secret@settler-host:5432/alex")


def test_settler_env_url_override() -> None:
    env = _settler_env(
        {
            "DELTAX_SETTLE_DATABASE_URL": "postgresql://deltax_settler:pw@host/alex",
            "DELTAX_SETTLE_DB_USER": "ignored",
        }
    )
    assert env["DELTAX_DATABASE_URL"] == "postgresql://deltax_settler:pw@host/alex"
