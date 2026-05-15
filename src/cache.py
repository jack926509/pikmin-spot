import hashlib
from collections import OrderedDict
from typing import Optional, Tuple

from src.models import Coords, PlaceCandidates

_MAX_ENTRIES = 512


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
    重覆觸發識別管線。"""

    def __init__(self) -> None:
        self._set: set[str] = set()

    def acquire(self, key: str) -> bool:
        if not key or key in self._set:
            return False
        self._set.add(key)
        return True

    def release(self, key: str) -> None:
        self._set.discard(key)

    def __contains__(self, key: str) -> bool:
        return key in self._set

    def __len__(self) -> int:
        return len(self._set)


image_cache = LRUResultCache()
in_flight = InFlightSet()
