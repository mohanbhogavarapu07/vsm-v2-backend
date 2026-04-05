import time
import logging
from typing import Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

class TTLCache:
    """
    Simple in-memory TTL cache to reduce redundant database roundtrips.
    """
    def __init__(self, ttl_seconds: int = 60):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self.ttl = ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            val, timestamp = self._cache[key]
            if (time.time() - timestamp) < self.ttl:
                return val
            else:
                # Expired
                del self._cache[key]
        return None

    def set(self, key: str, value: Any):
        self._cache[key] = (value, time.time())

    def invalidate(self, key: str):
        if key in self._cache:
            del self._cache[key]

    def clear(self):
        self._cache.clear()

# Singleton instances for different domains
permission_cache = TTLCache(ttl_seconds=30)  # Permissions change rarely
all_permissions_cache = TTLCache(ttl_seconds=300) # System permissions list
