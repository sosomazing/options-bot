"""Configuration: reads your settings and refuses anything unsafe.

How it works, in plain terms:
1. Your keys live in a file called ``.env`` (never in the code).
2. ``load_settings()`` reads that file and checks every value.
3. If anything points at LIVE trading, it raises ``LiveTradingRefusedError``
   and the program stops before it ever talks to Alpaca. This is "fail
   closed": when in doubt, do nothing.

The endpoints below come from alpaca-py 0.45.0's own ``BaseURL`` enum
(alpaca/common/enums.py); see also https://docs.alpaca.markets/ (Paper Trading):
    paper: https://paper-api.alpaca.markets
    live:  https://api.alpaca.markets   (always refused)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, Mapping
from urllib.parse import urlsplit

from dotenv import dotenv_values

from options_bot.errors import ConfigError, LiveTradingRefusedError

# ---------------------------------------------------------------------------
# Hard safety switches. These are constants on purpose: no setting, flag or
# environment variable can change them. Changing them is a code change that
# belongs to a later, reviewed stage.
# ---------------------------------------------------------------------------
PAPER_TRADING_URL: Final = "https://paper-api.alpaca.markets"
LIVE_TRADING_HOST: Final = "api.alpaca.markets"
TRADING_MODE: Final = "paper"
ORDER_SUBMISSION_ENABLED: Final = False

# Alpaca paper API key IDs start with "PK"; live key IDs start with "AK".
PAPER_KEY_PREFIX: Final = "PK"
LIVE_KEY_PREFIX: Final = "AK"

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_URL: Final = "sqlite:///data/options_bot.db"
_PLACEHOLDER_MARKERS: Final = ("your_", "_here", "changeme", "xxxx")
_VALID_LOG_LEVELS: Final = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Secret:
    """Holds a password-like value and hides it everywhere it could leak.

    ``print(secret)``, ``repr(secret)``, f-strings and logging all show
    ``'********'``. Call ``.reveal()`` only at the one place that must send
    the real value to Alpaca.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret('********')"

    def __str__(self) -> str:
        return "********"

    def __format__(self, _spec: str) -> str:
        return "********"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __reduce__(self):  # stops pickle/copy from writing the raw value out
        raise TypeError("Secret values cannot be pickled")


@dataclass(frozen=True)
class Settings:
    """Every setting the app uses, already checked. ``frozen`` = read-only."""

    api_key: Secret = field(repr=False)
    secret_key: Secret = field(repr=False)
    base_url: str = PAPER_TRADING_URL
    trading_mode: str = TRADING_MODE
    starting_balance: Decimal = Decimal("1000")
    database_url: str = DEFAULT_DATABASE_URL
    log_level: str = "INFO"

    @property
    def is_paper(self) -> bool:
        return self.trading_mode == TRADING_MODE and self.base_url == PAPER_TRADING_URL

    @property
    def order_submission_enabled(self) -> bool:
        return ORDER_SUBMISSION_ENABLED

    def secrets(self) -> list[str]:
        """Raw secret strings, used only by the log redaction filter."""
        return [self.api_key.reveal(), self.secret_key.reveal()]


# ---------------------------------------------------------------------------
# Individual checks. Each one raises a clear error, never echoing the secret.
# ---------------------------------------------------------------------------
def validate_base_url(raw: str | None) -> str:
    """Accept only the paper endpoint. Return it in one normal form."""
    if raw is None or raw.strip() == "":
        return PAPER_TRADING_URL

    value = raw.strip()
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()

    if host == LIVE_TRADING_HOST:
        raise LiveTradingRefusedError(
            "ALPACA_BASE_URL points at the LIVE endpoint (api.alpaca.markets). "
            "This project is paper-only. Use https://paper-api.alpaca.markets"
        )

    # People often copy ".../v2" from the docs; alpaca-py adds /v2 itself.
    path = parts.path.rstrip("/")
    ok = (
        parts.scheme == "https"
        and host == "paper-api.alpaca.markets"
        and parts.port is None
        and path in ("", "/v2")
        and not parts.query
        and not parts.fragment
        and parts.username is None
        and parts.password is None
    )
    if not ok:
        raise LiveTradingRefusedError(
            f"ALPACA_BASE_URL must be exactly {PAPER_TRADING_URL} (got {value!r}). "
            "Refusing to start."
        )
    return PAPER_TRADING_URL


def validate_trading_mode(raw: str | None) -> str:
    value = (raw or TRADING_MODE).strip().lower()
    if value != TRADING_MODE:
        raise LiveTradingRefusedError(
            f"TRADING_MODE must be 'paper' (got {value!r}). Live trading is not supported."
        )
    return value


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def validate_api_key(raw: str | None) -> Secret:
    value = (raw or "").strip()
    if not value:
        raise ConfigError("ALPACA_API_KEY is missing. Copy .env.example to .env and add your PAPER key ID.")
    if _looks_like_placeholder(value):
        raise ConfigError("ALPACA_API_KEY still has the example placeholder. Paste your real PAPER key ID.")
    if value.upper().startswith(LIVE_KEY_PREFIX):
        raise LiveTradingRefusedError(
            "ALPACA_API_KEY looks like a LIVE key (starts with 'AK'). "
            "Only paper keys (starting with 'PK') are accepted."
        )
    if not value.startswith(PAPER_KEY_PREFIX):
        raise LiveTradingRefusedError(
            "ALPACA_API_KEY does not look like a paper key (paper key IDs start with 'PK'). Refusing to start."
        )
    if any(ch.isspace() for ch in value):
        raise ConfigError("ALPACA_API_KEY contains spaces. Check for a copy/paste mistake.")
    return Secret(value)


def validate_secret_key(raw: str | None) -> Secret:
    value = (raw or "").strip()
    if not value:
        raise ConfigError("ALPACA_SECRET_KEY is missing. Add your PAPER secret key to .env.")
    if _looks_like_placeholder(value):
        raise ConfigError("ALPACA_SECRET_KEY still has the example placeholder. Paste your real PAPER secret.")
    if any(ch.isspace() for ch in value):
        raise ConfigError("ALPACA_SECRET_KEY contains spaces. Check for a copy/paste mistake.")
    return Secret(value)


def validate_starting_balance(raw: str | None) -> Decimal:
    try:
        value = Decimal((raw or "1000").strip())
    except InvalidOperation as exc:
        raise ConfigError(f"STARTING_BALANCE must be a number (got {raw!r}).") from exc
    if not value.is_finite() or value <= 0:
        raise ConfigError(f"STARTING_BALANCE must be greater than 0 (got {raw!r}).")
    return value


def validate_database_url(raw: str | None) -> str:
    value = (raw or DEFAULT_DATABASE_URL).strip()
    if not value.startswith("sqlite:///"):
        raise ConfigError("DATABASE_URL must be a local SQLite URL like sqlite:///data/options_bot.db")
    return value


def validate_log_level(raw: str | None) -> str:
    value = (raw or "INFO").strip().upper()
    if value not in _VALID_LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL must be one of {sorted(_VALID_LOG_LEVELS)} (got {raw!r}).")
    return value


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def load_settings(
    env: Mapping[str, str | None] | None = None,
    dotenv_path: Path | str | None = None,
) -> Settings:
    """Build checked ``Settings``.

    ``env``: pass a dict in tests. When omitted, values come from the ``.env``
    file in the project folder, and real environment variables win over it.
    """
    if env is None:
        path = Path(dotenv_path) if dotenv_path else PROJECT_ROOT / ".env"
        file_values = dotenv_values(path) if path.exists() else {}
        env = {**file_values, **os.environ}

    # Mode and URL first: a live setting must stop us even if keys are missing.
    trading_mode = validate_trading_mode(env.get("TRADING_MODE"))
    base_url = validate_base_url(env.get("ALPACA_BASE_URL"))

    # Older Alpaca examples use APCA_* names; refuse a live URL there too.
    validate_base_url(env.get("APCA_API_BASE_URL"))

    settings = Settings(
        api_key=validate_api_key(env.get("ALPACA_API_KEY")),
        secret_key=validate_secret_key(env.get("ALPACA_SECRET_KEY")),
        base_url=base_url,
        trading_mode=trading_mode,
        starting_balance=validate_starting_balance(env.get("STARTING_BALANCE")),
        database_url=validate_database_url(env.get("DATABASE_URL")),
        log_level=validate_log_level(env.get("LOG_LEVEL")),
    )

    if not settings.is_paper:  # belt and braces: should be impossible to reach
        raise LiveTradingRefusedError("Settings are not in paper mode. Refusing to start.")
    return settings
