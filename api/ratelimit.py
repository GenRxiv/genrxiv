"""
Rate limiting configuration for GenRxiv API.

Centralized so that auth.py and articles.py can import the limiter
without creating a circular import with main.py.
"""
import os

from slowapi import Limiter
from slowapi.util import get_remote_address


class _NoopLimiter:
    """No-op limiter for tests — decorators work but don't enforce limits."""
    def limit(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator


_rate_limit_enabled = os.environ.get("RATE_LIMIT_ENABLED", "true").lower() != "false"

if _rate_limit_enabled:
    limiter = Limiter(key_func=get_remote_address, default_limits=["200 per minute"])
else:
    limiter = _NoopLimiter()
