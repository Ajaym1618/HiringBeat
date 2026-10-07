"""
conftest.py — stub out beanie/motor/pymongo so that socket_events tests
can be collected without a live MongoDB or compatible motor installation.
"""
import sys
from unittest.mock import MagicMock, AsyncMock


# ---------------------------------------------------------------------------
# Build a minimal stub for the beanie.Document base class.
# We only need .get() and .find_one() as async class-methods.
# ---------------------------------------------------------------------------
class _FakeDocument:
    """Minimal beanie.Document stand-in for testing."""

    @classmethod
    async def get(cls, id):  # noqa: A002
        return None

    @classmethod
    async def find_one(cls, *args, **kwargs):
        return None

    async def insert(self):
        return self

    async def save(self):
        return self


# Stub modules that would fail to import due to motor/pymongo version mismatch
_beanie_stub = MagicMock()
_beanie_stub.Document = _FakeDocument
sys.modules.setdefault("beanie", _beanie_stub)

# motor stubs
_motor_stub = MagicMock()
sys.modules.setdefault("motor", _motor_stub)
sys.modules.setdefault("motor.motor_asyncio", _motor_stub)

# pymongo stubs (only if not already importable)
try:
    import pymongo  # noqa: F401
except ImportError:
    sys.modules.setdefault("pymongo", MagicMock())
    sys.modules.setdefault("pymongo.cursor", MagicMock())
