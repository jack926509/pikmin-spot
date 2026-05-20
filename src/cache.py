import hashlib
import time
from collections import OrderedDict
from typing import Optional, Tuple

from src.models import Coords, PlaceCandidates

_MAX_ENTRIES = 512
_IN_FLIGHT_TTL_SEC = 300.0  # 5 min;超時自動清理避免 stuck task 永遠卡住 file_id


class LRUResultCache:
    """Image bytes sha256 → (PlaceCandidates, Coords) 全管線結果快取。
    僅快取成功(有座標)的結果。"""

    def __init__(self, max_entries: int = _MAX_ENTRIES):
        self._data: OrderedDict[str, Tuple[PlaceCandidates, Coords]] = OrderedDict()
        self._max = max_entries

    def get(self, image_bytes: bytes) -> Optional[Tuple[PlaceCandidates, Coords]]:
        key = self._key(image_bytes)
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(
        self, image_bytes: bytes, place: PlaceCandidates, coords: Coords
    ) -> None:
        key = self._key(image_bytes)
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = (place, coords)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)

    @staticmethod
    def _key(image_bytes: bytes) -> str:
        return hashlib.sha256(image_bytes).hexdigest()


class InFlightSet:
    """簡單去重集合,防止同一 Slack file 被多個事件(message + file_shared)
    重覆觸發識別管線。

    v3.1:加 TTL —— 若 handler 因任何理由未呼叫 release(進程崩潰、卡住),
    entry 在 TTL 後自動失效,避免永遠卡住該 file_id。
    """

    def __init__(self, ttl_sec: float = _IN_FLIGHT_TTL_SEC) -> None:
        self._data: dict[str, float] = {}  # key -> expiry monotonic ts
        self._ttl = ttl_sec

    def _gc(self) -> None:
        now = time.monotonic()
        stale = [k for k, exp in self._data.items() if exp <= now]
        for k in stale:
            self._data.pop(k, None)

    def acquire(self, key: str) -> bool:
        if not key:
            return False
        self._gc()
        if key in self._data:
            return False
        self._data[key] = time.monotonic() + self._ttl
        return True

    def release(self, key: str) -> None:
        self._data.pop(key, None)

    def __contains__(self, key: str) -> bool:
        self._gc()
        return key in self._data

    def __len__(self) -> int:
        self._gc()
        return len(self._data)


image_cache = LRUResultCache()
in_flight = InFlightSet()
