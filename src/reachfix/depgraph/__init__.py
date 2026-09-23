"""DepGraph query layer: routing a question to graph traversal, advisory search, or both."""

from .dispatch import DepGraphContext
from .router import classify_query, load_context, route_query

__all__ = ["DepGraphContext", "classify_query", "load_context", "route_query"]
