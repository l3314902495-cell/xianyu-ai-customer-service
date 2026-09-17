from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import XianyuAccount


@dataclass(frozen=True)
class SendResult:
    success: bool
    external_message_id: str | None = None
    error: str | None = None
    outcome_unknown: bool = False


class XianyuAdapter(ABC):
    """Platform boundary; business services never access credentials/protocols."""

    adapter_type: str
    available: bool = True

    def __init__(self, account: XianyuAccount):
        self.account = account

    @abstractmethod
    async def connect(self) -> bool: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def get_accounts(self) -> list[dict]: ...

    @abstractmethod
    async def receive_message(self) -> dict | None: ...

    @abstractmethod
    async def send_message(
        self,
        conversation_id: str,
        content: str,
        reply_id: str,
        recipient_id: str | None = None,
    ) -> SendResult: ...

    @abstractmethod
    async def send_image_message(
        self,
        conversation_id: str,
        image_url: str,
        reply_id: str,
        recipient_id: str | None = None,
    ) -> SendResult: ...

    @abstractmethod
    async def get_product(self, product_id: str) -> dict | None: ...

    @abstractmethod
    async def get_conversation(self, conversation_id: str) -> dict | None: ...

    @abstractmethod
    async def get_user(self, user_id: str) -> dict | None: ...


class MockXianyuAdapter(XianyuAdapter):
    adapter_type = "mock"

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def get_accounts(self) -> list[dict]:
        return [{"id": self.account.external_account_id, "nickname": self.account.nickname, "status": "CONNECTED"}]

    async def receive_message(self) -> dict | None:
        return None

    async def send_message(
        self, conversation_id: str, content: str, reply_id: str, recipient_id: str | None = None
    ) -> SendResult:
        if not content.strip():
            return SendResult(False, error="不能发送空消息")
        return SendResult(True, f"mock-{self.account.id}-{reply_id}")

    async def send_image_message(
        self, conversation_id: str, image_url: str, reply_id: str, recipient_id: str | None = None
    ) -> SendResult:
        if not image_url.startswith("https://"):
            return SendResult(False, error="图片必须使用公网 HTTPS 地址")
        return SendResult(True, f"mock-image-{self.account.id}-{reply_id}")

    async def get_product(self, product_id: str) -> dict | None:
        return {"id": product_id, "account_id": self.account.external_account_id}

    async def get_conversation(self, conversation_id: str) -> dict | None:
        return {"id": conversation_id, "account_id": self.account.external_account_id}

    async def get_user(self, user_id: str) -> dict | None:
        return {"id": user_id}


class ExperimentalWebXianyuAdapter(XianyuAdapter):
    """Non-official, user-confirmed web text channel. Stops on verification/risk."""

    adapter_type = "experimental-web"

    async def connect(self) -> bool:
        from app.services.xianyu_control import connect_account

        return await connect_account(self.account.id)

    async def disconnect(self) -> None:
        from app.services.xianyu_control import disconnect_account

        await disconnect_account(self.account.id)

    async def get_accounts(self) -> list[dict]:
        return [{"id": self.account.external_account_id, "nickname": self.account.nickname}]

    async def receive_message(self) -> dict | None:
        return None

    async def send_message(
        self, conversation_id: str, content: str, reply_id: str, recipient_id: str | None = None
    ) -> SendResult:
        from app.services.xianyu_control import send_text

        if not recipient_id:
            return SendResult(False, error="会话缺少买家 ID")
        try:
            external_id = await send_text(
                self.account.id, conversation_id, recipient_id, content
            )
            return SendResult(True, external_id)
        except Exception as exc:
            return SendResult(False, error=str(exc), outcome_unknown=isinstance(exc, TimeoutError))

    async def send_image_message(
        self, conversation_id: str, image_url: str, reply_id: str, recipient_id: str | None = None
    ) -> SendResult:
        from app.services.xianyu_control import send_image

        if not recipient_id:
            return SendResult(False, error="会话缺少买家 ID")
        if not image_url.startswith("https://"):
            return SendResult(False, error="图片必须使用公网 HTTPS 地址")
        try:
            external_id = await send_image(
                self.account.id, conversation_id, recipient_id, image_url
            )
            return SendResult(True, external_id)
        except Exception as exc:
            return SendResult(False, error=str(exc), outcome_unknown=isinstance(exc, TimeoutError))

    async def get_product(self, product_id: str) -> dict | None:
        return None

    async def get_conversation(self, conversation_id: str) -> dict | None:
        return None

    async def get_user(self, user_id: str) -> dict | None:
        return None


class RealXianyuAdapter(XianyuAdapter):
    """Reserved for a documented, authorized official integration."""

    adapter_type = "real"
    available = False

    @staticmethod
    def _missing() -> RuntimeError:
        return RuntimeError("尚未配置官方或已授权的合规真实闲鱼接口")

    async def connect(self) -> bool:
        raise self._missing()

    async def disconnect(self) -> None:
        raise self._missing()

    async def get_accounts(self) -> list[dict]:
        raise self._missing()

    async def receive_message(self) -> dict | None:
        raise self._missing()

    async def send_message(
        self, conversation_id: str, content: str, reply_id: str, recipient_id: str | None = None
    ) -> SendResult:
        raise self._missing()

    async def send_image_message(
        self, conversation_id: str, image_url: str, reply_id: str, recipient_id: str | None = None
    ) -> SendResult:
        raise self._missing()

    async def get_product(self, product_id: str) -> dict | None:
        raise self._missing()

    async def get_conversation(self, conversation_id: str) -> dict | None:
        raise self._missing()

    async def get_user(self, user_id: str) -> dict | None:
        raise self._missing()


def adapter_for_account(account: XianyuAccount) -> XianyuAdapter:
    adapters = {
        "mock": MockXianyuAdapter,
        "experimental-web": ExperimentalWebXianyuAdapter,
        "real": RealXianyuAdapter,
    }
    adapter = adapters.get(account.adapter_type)
    if not adapter:
        raise ValueError(f"不支持的闲鱼 Adapter 类型：{account.adapter_type}")
    return adapter(account)
