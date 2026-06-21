"""Carter AI — workspace scaffolding and management."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("carter-ai")
except PackageNotFoundError:  # running from a source tree without installed metadata
    __version__ = "0+unknown"
