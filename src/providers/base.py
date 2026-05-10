from abc import ABC, abstractmethod
from typing import Optional

from src.config import settings
from src.models import Coords

HTTP_TIMEOUT_SEC = 8.0
USER_AGENT = f"PikminCoordBot/1.0 ({settings.CONTACT_EMAIL})"


class GeocoderProvider(ABC):
    name: str

    @abstractmethod
    async def lookup(self, query: str, hint_country: str = "") -> Optional[Coords]:
        """單次查詢。找不到回 None,網路錯誤拋 ProviderError。"""


class ProviderError(Exception):
    pass
