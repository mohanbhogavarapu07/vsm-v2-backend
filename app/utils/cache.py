import time
import logging
import hashlib
import json
from typing import Dict, Any, Tuple, Optional, Callable
from functools import wraps

logger = logging.getLogger(__name__)

class TTLCache:
    """
    Simple in-memory TTL cache to reduce redundant database roundtrips.
    """
    def __init__(self, ttl_seconds: int = 60):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self.ttl = ttl_seconds
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            val, timestamp = self._cache[key]
            if (time.time() - timestamp) < self.ttl:
                self._hits += 1
                return val
            else:
                # Expired
                del self._cache[key]
        self._misses += 1
        return None

    def set(self, key: str, value: Any):
        self._cache[key] = (value, time.time())

    def invalidate(self, key: str):
        if key in self._cache:
            del self._cache[key]

    def clear(self):
        self._cache.clear()
        
    def get_stats(self) -> dict:
        """Return cache statistics for monitoring."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{hit_rate:.2f}%",
            "size": len(self._cache)
        }


def make_cache_key(*args, **kwargs) -> str:
    """
    Generate a stable cache key from function arguments.
    Handles serialization of common types.
    """
    key_data = {
        "args": [str(arg) for arg in args],
        "kwargs": {k: str(v) for k, v in sorted(kwargs.items())}
    }
    key_str = json.dumps(key_data, sort_keys=True)
    return hashlib.md5(key_str.encode()).hexdigest()


def cached_response(cache: TTLCache, key_prefix: str = ""):
    """
    Decorator for caching async function responses.
    
    Usage:
        @cached_response(response_cache, key_prefix="tasks")
        async def list_tasks(...):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key from function name + arguments
            cache_key = f"{key_prefix}:{func.__name__}:{make_cache_key(*args, **kwargs)}"
            
            # Check cache
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache HIT: {cache_key}")
                return cached
            
            # Cache miss - execute function
            logger.debug(f"Cache MISS: {cache_key}")
            result = await func(*args, **kwargs)
            
            # Store in cache
            cache.set(cache_key, result)
            return result
            
        return wrapper
    return decorator


# Singleton instances for different domains
permission_cache = TTLCache(ttl_seconds=30)  # Permissions change rarely
all_permissions_cache = TTLCache(ttl_seconds=300)  # System permissions list

# Response-level caches for API endpoints
task_cache = TTLCache(ttl_seconds=30)  # Task data changes frequently
team_cache = TTLCache(ttl_seconds=300)  # Team/project structure changes rarely
github_cache = TTLCache(ttl_seconds=300)  # GitHub repository data
sprint_cache = TTLCache(ttl_seconds=60)  # Sprint data moderate frequency
