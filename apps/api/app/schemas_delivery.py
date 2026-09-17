from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DeliveryConfigUpdate(BaseModel):
    enabled: bool = False
    delivery_type: str = "card"
    message_template: str = "感谢购买，您的卡密是：{content}"
    image_url: str | None = None

    @field_validator("delivery_type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in {"card", "image"}:
            raise ValueError("仅支持 card 或 image")
        return value

    @field_validator("message_template")
    @classmethod
    def validate_template(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 2000:
            raise ValueError("发货话术不能为空且不能超过 2000 字")
        return value


class CardInventoryCreate(BaseModel):
    contents: list[str] = Field(min_length=1, max_length=1000)


class MockPaidOrderRequest(BaseModel):
    product_id: str
    buyer_id: str
    conversation_id: str | None = None
    external_order_id: str | None = None


class DeliveryResolutionRequest(BaseModel):
    action: Literal["mark_sent", "release"]
    external_message_id: str | None = Field(default=None, max_length=200)
