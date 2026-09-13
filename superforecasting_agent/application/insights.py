"""Shared argument contract for session usage insights."""

import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class InsightsQuery:
    days: int = 30
    source: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.days, bool)
            or not isinstance(self.days, int)
            or self.days <= 0
        ):
            raise ValueError("Insights days must be a positive integer.")
        if self.source is not None and (
            not isinstance(self.source, str) or not self.source.strip()
        ):
            raise ValueError("Insights source must be a nonempty string.")


def parse_insights_arguments(argument: str) -> InsightsQuery:
    tokens = shlex.split(argument)
    days = 30
    source = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token[:1] in {"‒", "–", "—", "―"} and token[1:] in {"days", "source"}:
            token = "--" + token[1:]
        if token in {"--days", "--source"}:
            if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
                raise ValueError(f"Missing value for {token}.")
            value = tokens[index + 1]
            if token == "--source":
                source = value
            else:
                try:
                    days = int(value)
                except ValueError as exc:
                    raise ValueError(f"Invalid --days value: {value}") from exc
            index += 2
        elif token.isdecimal():
            days = int(token)
            index += 1
        else:
            raise ValueError(f"Unknown insights argument: {token}")
    return InsightsQuery(days, source)
