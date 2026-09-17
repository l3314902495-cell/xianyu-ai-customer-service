from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Intent(StrEnum):
    greeting = "greeting"
    product_information = "product_information"
    product_specification = "product_specification"
    product_condition = "product_condition"
    product_compatibility = "product_compatibility"
    product_usage = "product_usage"
    inventory = "inventory"
    shipping = "shipping"
    logistics = "logistics"
    price = "price"
    price_negotiation = "price_negotiation"
    order = "order"
    after_sales = "after_sales"
    refund = "refund"
    complaint = "complaint"
    product_comparison = "product_comparison"
    clarification = "clarification"
    thanks = "thanks"
    small_talk = "small_talk"
    unknown = "unknown"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ResponseAction(StrEnum):
    REPLY = "REPLY"
    SILENT = "SILENT"
    ANALYZE_ONLY = "ANALYZE_ONLY"


class AIReplyDecision(BaseModel):
    reply: str = Field(min_length=1, max_length=4000)
    should_send: bool
    need_human: bool
    need_clarification: bool = False
    knowledge_gap: bool
    missing_knowledge: str | None = None
    intent: Intent
    risk_level: RiskLevel
    risk_flag: str | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str
    response_action: ResponseAction = ResponseAction.REPLY
    silence_reason: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class XianyuAccountCreate(BaseModel):
    nickname: str = Field(min_length=1, max_length=120)
    external_account_id: str = Field(min_length=1, max_length=120)
    adapter_type: Literal["mock", "real", "experimental-web"] = "mock"
    ai_enabled: bool = True


class XianyuAccountUpdate(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=120)
    external_account_id: str | None = Field(default=None, min_length=1, max_length=120)
    ai_enabled: bool | None = None


class XianyuCookieImport(BaseModel):
    cookie_text: str = Field(min_length=20, max_length=30000)


class ProductCreate(BaseModel):
    account_id: str
    external_product_id: str
    name: str
    category: str | None = None
    image_url: str | None = None
    price: float = 0
    ai_enabled: bool = True
    ai_prompt: str = ""
    details: dict[str, Any] = {}


class ProductUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    image_url: str | None = None
    price: float | None = None
    ai_enabled: bool | None = None
    ai_prompt: str | None = None
    status: Literal["ACTIVE", "DISABLED"] | None = None
    details: dict[str, Any] | None = None


class KnowledgeCreate(BaseModel):
    title: str
    content: str
    category: str = "other"
    priority: int = 0
    enabled: bool = True
    source: str = "manual"


class FAQCreate(BaseModel):
    question: str
    answer: str
    keywords: list[str] = []
    enabled: bool = True
    priority: int = 0


class SimulatorRequest(BaseModel):
    account_id: str
    product_id: str
    buyer_id: str = "mock-buyer-001"
    buyer_nickname: str = "模拟买家"
    content: str
    external_message_id: str | None = None


class HumanReplyRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    suggestion_id: str | None = None


class AITestRequest(BaseModel):
    product_id: str
    message: str


class ProviderUpdate(BaseModel):
    provider: str
    base_url: str = ""
    api_key: str = ""
    clear_api_key: bool = False
    model_name: str
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(ge=64, le=8192)
    timeout: int = Field(ge=1, le=120)


class GlobalPromptUpdate(BaseModel):
    content: str = Field(min_length=20, max_length=20000)


class KnowledgeGapResolve(BaseModel):
    title: str
    content: str
    category: str = "other"


class SystemSwitch(BaseModel):
    enabled: bool


class ReplyRulesUpdate(BaseModel):
    minimum_confidence: float = Field(default=0.65, ge=0, le=1)
    shop_rules: str = Field(default="不得承诺退款、赔偿、改价或修改订单。", max_length=5000)
    price_negotiation_reply: str = Field(default="价格这块我帮你留给卖家本人确认哈。", min_length=1, max_length=500)
    knowledge_gap_reply: str = Field(default="这个具体信息我这边暂时没有记录，我帮你转给卖家确认一下。", min_length=1, max_length=500)
    forbidden_reply_phrases: list[str] = Field(default_factory=list, max_length=50)
    smart_silence_enabled: bool = True
    silence_acknowledgements: bool = True
    silence_thanks: bool = True
    silence_emoji_only: bool = True
    silence_custom_phrases: list[str] = Field(default_factory=list, max_length=50)
    silence_confidence_threshold: float = Field(default=0.85, ge=0.5, le=1)
    greeting_cooldown_minutes: int = Field(default=10, ge=1, le=120)


class RuntimeSettingsUpdate(BaseModel):
    debounce_ms: int = Field(default=1500, ge=1000, le=3000)
    history_limit: int = Field(default=16, ge=10, le=20)
    ignored_message_prefixes: list[str] = Field(default_factory=list, max_length=30)
