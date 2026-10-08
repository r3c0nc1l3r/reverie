"""Laya (local) or Jev (hosted) chooses an observed action. Code owns execution."""

__version__ = "0.1.0"  # x-release-please-version

from .agent import Agent
from .browser import Browser

__all__ = ["Agent", "Browser", "__version__"]
