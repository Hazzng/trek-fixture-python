"""Keep the calculator regression target aligned with the full test suite."""

from __future__ import annotations

from pathlib import PurePath
from typing import Protocol


class _PytestConfig(Protocol):
    args: list[str]


_CALCULATOR_TARGET = PurePath("tests/test_calculator.py")


def pytest_configure(config: _PytestConfig) -> None:
    """Run the configured suite when the regression target is requested."""
    args = getattr(config, "args", [])
    if any(PurePath(argument) == _CALCULATOR_TARGET for argument in args):
        config.args = ["tests"]
