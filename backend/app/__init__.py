"""Haularr."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("haularr")  # single source: pyproject.toml
except PackageNotFoundError:  # not installed (e.g. bare source tree)
    __version__ = "0.0.0"
