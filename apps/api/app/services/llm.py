import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from app.schemas import AIReplyDecision, Intent, ResponseAction, RiskLevel
from app.services.prompt_builder import BuiltPrompt

DECISION_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_customer_service_decision",
        "description": "提交完整的闲鱼客服回复和后端决策字段",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "reply": {"type": "string"},
                "should_send": {"type": "boolean"},
                "need_human": {"type": "boolean"},
                "need_clarification": {"type": "boolean"},
                "knowledge_gap": {"type": "boolean"},
                "missing_knowledge": {"type": ["string", "null"]},
                "intent": {"type": "string", "enum": [item.value for item in Intent]},
                "risk_level": {"type": "string", "enum": [item.value for item in RiskLevel]},
                "risk_flag": {"type": ["string", "null"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string"},
                "response_action": {"type": "string", "enum": [item.value for item in ResponseAction]},
                "silence_reason": {"type": ["string", "null"]},
            },
            "required": [
                "reply",
                "should_send",
                "need_human",
                "need_clarification",
                "knowledge_gap",
                "missing_knowledge",
                "intent",
                "risk_level",
                "risk_flag",
                "confidence",
                "reason",
                "response_action",
                "silence_reason",
            ],
        },
    },
}


@dataclass
class ProviderResult:
    decision: AIReplyDecision
    raw: dict
    input_tokens: int = 0
    output_tokens: int = 0


class StructuredOutputError(RuntimeError):
    """The provider answered, but did not return a complete decision object."""

    def __init__(self, provider: str, model: str, raw_text: str):
        super().__init__("模型连续两次未返回完整的结构化决策，已禁止自动发送")
        self.provider = provider
        self.model = model
        self.raw_text = raw_text[:8000]

    @property
    def partial_reply(self) -> str | None:
        try:
            match = re.search(r"\{.*\}", self.raw_text, re.S)
            value = json.loads(match.group(0) if match else self.raw_text)
        except (ValueError, TypeError, json.JSONDecodeError):
            return None
        reply = value.get("reply") if isinstance(value, dict) else None
        return reply.strip()[:4000] if isinstance(reply, str) and reply.strip() else None


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def generate_reply(self, prompt: BuiltPrompt) -> ProviderResult: ...

    @abstractmethod
    async def test_connection(self) -> tuple[bool, str]: ...


def parse_decision(raw_text: str) -> AIReplyDecision:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    try:
        return AIReplyDecision.model_validate_json(cleaned)
    except (ValidationError, ValueError):
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise ValueError("模型未返回 JSON") from None
        return AIReplyDecision.model_validate(json.loads(match.group(0)))


def recover_partial_decision(raw_text: str) -> AIReplyDecision:
    """Use a useful model reply even when a compatible provider omits decision fields."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    match = re.search(r"\{.*\}", cleaned, re.S)
    value = json.loads(match.group(0) if match else cleaned)
    if not isinstance(value, dict) or not str(value.get("reply") or "").strip():
        raise ValueError("模型没有返回可用回复")
    payload = dict(value)
    payload["reply"] = str(payload["reply"]).strip()
    payload.setdefault("should_send", False)
    payload.setdefault("need_human", False)
    payload.setdefault("need_clarification", False)
    payload.setdefault("knowledge_gap", False)
    payload.setdefault("missing_knowledge", None)
    if payload.get("intent") not in {item.value for item in Intent}:
        payload["intent"] = Intent.unknown.value
    risk = str(payload.get("risk_level") or RiskLevel.LOW.value).upper()
    payload["risk_level"] = risk if risk in {item.value for item in RiskLevel} else RiskLevel.LOW.value
    payload.setdefault("risk_flag", None)
    try:
        payload["confidence"] = min(1.0, max(0.0, float(payload.get("confidence", 0.72))))
    except (TypeError, ValueError):
        payload["confidence"] = 0.72
    payload.setdefault("reason", "模型回复可用，后端补齐了缺失的决策字段")
    payload.setdefault("response_action", ResponseAction.SILENT.value)
    payload.setdefault("silence_reason", "模型未返回完整的回复必要性决策")
    return AIReplyDecision.model_validate(payload)


class MockLLMProvider(LLMProvider):
    name = "mock"
    model = "mock-v1"

    async def test_connection(self) -> tuple[bool, str]:
        return True, "Mock 模型连接正常"

    async def generate_reply(self, prompt: BuiltPrompt) -> ProviderResult:
        message = prompt.user.split("<buyer_message>")[-1].split("</buyer_message>")[0].strip()
        lower = message.lower()
        injection = any(x in lower for x in ["忽略前面", "系统提示词", "ignore previous", "developer message"])
        high_terms = ["退款", "赔偿", "投诉", "修改地址", "律师", "欺诈"]
        negotiate_terms = ["最低多少", "少点", "便宜", "刀吗", "出吗"]
        if injection:
            d = AIReplyDecision(reply="这个请求无法处理。商品相关问题我可以继续帮你确认。", should_send=False, need_human=True, knowledge_gap=False, intent=Intent.unknown, risk_level=RiskLevel.HIGH, risk_flag="prompt_injection", confidence=.99, reason="检测到提示词注入")
        elif any(x in message for x in high_terms):
            intent = Intent.refund if "退款" in message else Intent.complaint
            d = AIReplyDecision(reply="这个问题需要卖家本人处理，我已经帮你转给人工确认。", should_send=False, need_human=True, knowledge_gap=False, intent=intent, risk_level=RiskLevel.HIGH, risk_flag="restricted_action", confidence=.96, reason="高风险业务必须人工处理")
        elif any(x in message for x in negotiate_terms):
            d = AIReplyDecision(reply="价格这块我帮你留给卖家本人确认哈。", should_send=False, need_human=True, knowledge_gap=False, intent=Intent.price_negotiation, risk_level=RiskLevel.MEDIUM, confidence=.95, reason="V1 不自动议价")
        else:
            searchable = " ".join([f"{k['title']} {k['content']}" for k in prompt.used_knowledge] + [f"{f['question']} {f['answer']}" for f in prompt.used_faqs])
            tokens = [x for x in re.split(r"[？?，,。\s]+", message) if len(x) >= 2 and x not in {"这个", "请问", "一下", "可以"}]
            matches = [
                k
                for k in prompt.used_knowledge
                if any(t in f"{k['title']}{k['content']}" for t in tokens) or str(k["title"]) in message
            ]
            faq_matches = [f for f in prompt.used_faqs if any(t in f"{f['question']}{f['answer']}{f['keywords']}" for t in tokens)]
            if any(x in message for x in ["还有吗", "有货", "在吗"]):
                d = AIReplyDecision(reply="还在的，可以直接拍。", should_send=True, need_human=False, knowledge_gap=False, intent=Intent.inventory, risk_level=RiskLevel.LOW, confidence=.9, reason="库存问候规则")
            elif any(x in message for x in ["舒服", "保暖", "冬天", "穿着感受", "手感"]):
                if "羊毛" in searchable:
                    d = AIReplyDecision(
                        reply="可以的，这件羊毛含量高，冬天穿保暖性和舒适度都不错，里面搭件打底就很合适；特别冷或长时间在户外再加件外套更稳妥。",
                        should_send=True,
                        need_human=False,
                        knowledge_gap=False,
                        intent=Intent.product_usage,
                        risk_level=RiskLevel.LOW,
                        confidence=.86,
                        reason="依据已知羊毛材质和稳定的穿着常识给出低风险体验建议",
                    )
                else:
                    d = AIReplyDecision(
                        reply="日常穿着的舒适度没问题。你如果比较怕冷，告诉我大概在哪个城市、平时是通勤还是长时间户外，我可以再帮你判断怎么搭更合适。",
                        should_send=True,
                        need_human=False,
                        need_clarification=True,
                        knowledge_gap=False,
                        intent=Intent.clarification,
                        risk_level=RiskLevel.LOW,
                        confidence=.76,
                        reason="低风险体验问题可先给建议，并通过一个问题补充使用场景",
                    )
            elif matches or faq_matches:
                answer = (faq_matches[0]["answer"] if faq_matches else matches[0]["content"])
                d = AIReplyDecision(reply=f"有记录的：{answer}", should_send=True, need_human=False, knowledge_gap=False, intent=Intent.product_information, risk_level=RiskLevel.LOW, confidence=.9, reason="商品知识中存在明确答案")
            else:
                topic = message[:80]
                d = AIReplyDecision(reply="这个具体信息我这边暂时没有记录，我帮你转给卖家确认一下。", should_send=False, need_human=True, knowledge_gap=True, missing_knowledge=topic, intent=Intent.unknown, risk_level=RiskLevel.MEDIUM, confidence=.35, reason=f"商品知识中无匹配事实（知识字符数 {len(searchable)}）")
        return ProviderResult(d, d.model_dump(mode="json"), len(prompt.system + prompt.user) // 4, len(d.reply) // 2)


class OpenAICompatibleProvider(LLMProvider):
    name = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: int,
        provider_name: str = "openai-compatible",
    ):
        self.name = provider_name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    @property
    def chat_completions_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def _request(
        self,
        prompt: BuiltPrompt,
        repair_output: str | None = None,
        json_mode: bool = True,
    ) -> dict:
        messages = [{"role": "system", "content": prompt.system}, {"role": "user", "content": prompt.user}]
        if repair_output is not None:
            messages.extend(
                [
                    {"role": "assistant", "content": repair_output[:8000]},
                    {
                        "role": "system",
                        "content": (
                            "上一次输出缺少必填字段。重新生成完整 JSON，不能只返回 reply，不能输出 Markdown 或解释。"
                            "必须严格包含以下字段和类型："
                            '{"reply":"给买家的回复","should_send":false,"need_human":true,'
                            '"need_clarification":false,"knowledge_gap":false,"missing_knowledge":null,'
                            '"intent":"unknown","risk_level":"MEDIUM","risk_flag":null,'
                            '"confidence":0.5,"reason":"决策依据"}。'
                            "intent 和 risk_level 必须使用系统规则中允许的枚举值。"
                        ),
                    },
                ]
            )
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if repair_output is not None:
            payload["tools"] = [DECISION_TOOL]
            payload["tool_choice"] = {
                "type": "function",
                "function": {"name": "submit_customer_service_decision"},
            }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.chat_completions_url,
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def generate_reply(self, prompt: BuiltPrompt) -> ProviderResult:
        last_error: Exception | None = None
        last_raw_text = ""
        for attempt in range(2):
            try:
                # Some OpenAI-compatible providers do not implement
                # response_format. The retry uses prompt-enforced JSON only.
                data = await self._request(
                    prompt,
                    repair_output=last_raw_text if attempt == 1 else None,
                    json_mode=attempt == 0,
                )
                message = data["choices"][0]["message"]
                tool_calls = message.get("tool_calls") or []
                if tool_calls:
                    content = tool_calls[0]["function"]["arguments"]
                else:
                    content = message.get("content", "")
                last_raw_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                decision = parse_decision(last_raw_text)
                usage = data.get("usage", {})
                return ProviderResult(decision, decision.model_dump(mode="json"), usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
            except httpx.TimeoutException as exc:
                raise RuntimeError(
                    f"模型请求超时：{self.timeout} 秒内未收到完整响应"
                ) from exc
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                raise RuntimeError(f"模型接口请求失败：{type(exc).__name__}") from exc
            except Exception as exc:
                last_error = exc
        if last_raw_text:
            try:
                decision = recover_partial_decision(last_raw_text)
                return ProviderResult(
                    decision,
                    {
                        **decision.model_dump(mode="json"),
                        "structured_output_recovered": True,
                        "provider_raw_text": last_raw_text[:4000],
                    },
                )
            except (ValueError, ValidationError, json.JSONDecodeError):
                raise StructuredOutputError(self.name, self.model, last_raw_text) from last_error
        raise RuntimeError(f"模型请求失败: {type(last_error).__name__ if last_error else 'UnknownError'}") from last_error

    async def test_connection(self) -> tuple[bool, str]:
        if not self.base_url or not self.api_key or not self.model:
            return False, "Base URL、API Key 和 Model Name 均不能为空"
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.chat_completions_url,
                    headers=self._headers(),
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": "Reply with OK."}],
                        "temperature": 0,
                        "max_tokens": 8,
                    },
                )
                response.raise_for_status()
                data = response.json()
                if not data.get("choices"):
                    return False, "接口已响应，但返回格式不是 Chat Completions"
            latency_ms = round((time.perf_counter() - started) * 1000)
            return True, f"连接成功：{self.model}（{latency_ms} ms）"
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            hints = {
                401: "API Key 无效或已过期",
                403: "API Key 没有调用权限",
                404: "Base URL 或模型名称不正确",
                429: "请求过于频繁、额度不足或账户欠费",
            }
            return False, f"连接失败：{hints.get(status, f'上游返回 HTTP {status}')}"
        except httpx.TimeoutException:
            return False, f"连接超时：{self.timeout} 秒内未收到响应"
        except httpx.InvalidURL:
            return False, "Base URL 格式不正确"
        except Exception as exc:
            return False, f"连接失败：{type(exc).__name__}"
