"""Trek fixture library — a tiny, deterministic Python package for the spike."""

from .calculator import add, divide, multiply, power, subtract
from .strings import slugify

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "add",
    "subtract",
    "multiply",
    "divide",
    "power",
    "slugify",
]
