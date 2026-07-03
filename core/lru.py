"""Thread-safe bounded LRU used for all in-process response caches."""
from collections import OrderedDict
import threading


class BoundedLRU(OrderedDict):
    """Thread-safe bounded LRU.

    Python dict ops are atomic under the GIL for single-key access, but the
    move_to_end + popitem dance below is not — so we guard with a lock to
    keep multiple Flask worker threads from corrupting the order map. All
    locked methods call OrderedDict super().* directly to avoid re-entering
    the lock from one method into another.
    """
    def __init__(self, maxsize: int):
        super().__init__()
        self._maxsize = maxsize
        self._lock = threading.Lock()

    def get(self, key, default=None):  # type: ignore[override]
        with self._lock:
            if OrderedDict.__contains__(self, key):
                self.move_to_end(key)
                return OrderedDict.__getitem__(self, key)
            return default

    def __contains__(self, key):  # type: ignore[override]
        with self._lock:
            return OrderedDict.__contains__(self, key)

    def __getitem__(self, key):  # type: ignore[override]
        with self._lock:
            value = OrderedDict.__getitem__(self, key)
            self.move_to_end(key)
            return value

    def __setitem__(self, key, value):  # type: ignore[override]
        with self._lock:
            if OrderedDict.__contains__(self, key):
                self.move_to_end(key)
            OrderedDict.__setitem__(self, key, value)
            while len(self) > self._maxsize:
                self.popitem(last=False)


# Historical name used across the app.
_BoundedLRU = BoundedLRU
