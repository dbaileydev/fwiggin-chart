from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class PineMetadata:
    strategy_name: str
    initial_capital: float
    version: int | None
    is_strategy: bool


_STRATEGY_RE = re.compile(
    r'strategy\s*\(\s*"([^"]+)"',
    re.IGNORECASE,
)
_INDICATOR_RE = re.compile(
    r'indicator\s*\(\s*"([^"]+)"',
    re.IGNORECASE,
)
_CAPITAL_RE = re.compile(
    r"initial_capital\s*=\s*([\d.]+)",
    re.IGNORECASE,
)
_VERSION_RE = re.compile(r"//@version\s*=\s*(\d+)")


def parse_pine(source: str) -> PineMetadata:
    strategy_match = _STRATEGY_RE.search(source)
    indicator_match = _INDICATOR_RE.search(source)
    capital_match = _CAPITAL_RE.search(source)
    version_match = _VERSION_RE.search(source)

    name = "Unknown Strategy"
    is_strategy = False
    if strategy_match:
        name = strategy_match.group(1)
        is_strategy = True
    elif indicator_match:
        name = indicator_match.group(1)

    initial_capital = float(capital_match.group(1)) if capital_match else 50_000.0
    version = int(version_match.group(1)) if version_match else None

    return PineMetadata(
        strategy_name=name,
        initial_capital=initial_capital,
        version=version,
        is_strategy=is_strategy,
    )
