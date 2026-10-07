"""Typed analysis failures that may be recovered by changing the request."""

class OutputLimitError(ValueError):
    """The provider truncated its answer at the output token limit."""
