"""All the error types the bot raises, in one place.

Having our own error classes lets the rest of the code (and you, reading the
logs) tell "your settings are wrong" apart from "Alpaca is down".
"""


class OptionsBotError(Exception):
    """Base class for every error this project raises on purpose."""


class ConfigError(OptionsBotError):
    """Settings are missing or unsafe. The program refuses to start."""


class LiveTradingRefusedError(ConfigError):
    """Something pointed at live trading (URL, keys or mode). Always fatal."""


class BrokerError(OptionsBotError):
    """Alpaca answered with an error (bad keys, account problem, etc.)."""


class BrokerConnectionError(BrokerError):
    """Could not reach Alpaca at all (no internet, DNS, timeout)."""


class OrderSubmissionDisabledError(OptionsBotError):
    """Raised if any code tries to place, change or cancel an order in stage 1."""
