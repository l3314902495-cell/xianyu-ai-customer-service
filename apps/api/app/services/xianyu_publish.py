"""Human-confirmed publishing through the user's experimental Xianyu web session.

The protocol is unofficial and deliberately fail-closed: no retries are made for
the final publish request and verification/risk responses are never bypassed.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

import requests

from app.models import XianyuAccount, XianyuAccountCredential
from app.secrets import decrypt_secret
from app.services.xianyu_protocol import WebSession, generate_device_id, mtop_call

UPLOAD_URL = "https://stream-upload.goofish.com/api/upload.api"
CATEGORY_API = "mtop.taobao.idle.kgraph.property.recommend"
PUBLISH_API = "mtop.idle.pc.idleitem.publish"


class PublishOutcomeUnknown(RuntimeError):
    """The final request may have reached Xianyu; a duplicate must not be sent."""


@dataclass(frozen=True)
class PublishImage:
    name: str
    content_type: str
    content: bytes


def session_from_credential(
    account: XianyuAccount, credential: XianyuAccountCredential
) -> WebSession:
    try:
        payload = json.loads(decrypt_secret(credential.encrypted_payload))
        cookies = payload["cookies"]
        unb = str(cookies["unb"])
    except Exception as exc:
        raise RuntimeError("账号登录凭据无法解密，请重新扫码") from exc
    http = requests.Session()
    http.trust_env = False
    http.cookies.update(cookies)
    return WebSession(
        http=http,
        unb=unb,
        tracknick=unquote(str(cookies.get("tracknick", ""))),
        device_id=str(payload.get("device_id") or generate_device_id(unb)),
    )


def _upload_image(session: WebSession, image: PublishImage) -> dict[str, Any]:
    response = session.http.post(
        UPLOAD_URL,
        headers={
            "accept": "*/*",
            "origin": "https://www.goofish.com",
            "referer": "https://www.goofish.com/publish",
        },
        params={"floderId": "0", "appkey": "xy_chat", "_input_charset": "utf-8"},
        files={"file": (image.name, image.content, image.content_type)},
        timeout=60,
    )
    response.raise_for_status()
    raw = response.json()
    obj = raw.get("object") or {}
    url = str(obj.get("url") or "").strip()
    if not url:
        raise RuntimeError("闲鱼没有返回图片地址，请重新选择图片")
    try:
        width, height = (int(value) for value in str(obj.get("pix") or "0x0").split("x", 1))
    except (TypeError, ValueError):
        width = height = 0
    if width <= 0 or height <= 0:
        raise RuntimeError(f"闲鱼无法识别图片尺寸：{image.name}")
    return {"url": url, "width": width, "height": height}


def _image_info(image: dict[str, Any]) -> dict[str, Any]:
    return {
        "extraInfo": {"isH": "false", "isT": "false", "raw": "false"},
        "isQrCode": False,
        "url": image["url"],
        "heightSize": image["height"],
        "widthSize": image["width"],
        "major": True,
        "type": 0,
        "status": "done",
    }


def _recommend_category(session: WebSession, title: str, images: list[dict[str, Any]]) -> dict[str, str]:
    raw = mtop_call(
        session,
        CATEGORY_API,
        {
            "title": title,
            "lockCpv": False,
            "multiSKU": False,
            "publishScene": "mainPublish",
            "scene": "newPublishChoice",
            "description": title,
            "imageInfos": [_image_info(image) for image in images],
            "uniqueCode": str(time.time_ns()),
        },
        version="2.0",
    )
    predicted = (raw.get("data") or {}).get("categoryPredictResult") or {}
    result = {
        "cat_id": str(predicted.get("catId") or ""),
        "cat_name": str(predicted.get("catName") or ""),
        "channel_cat_id": str(predicted.get("channelCatId") or ""),
        "tb_cat_id": str(predicted.get("tbCatId") or ""),
    }
    if not all(result.values()):
        raise RuntimeError("闲鱼未能识别商品类目，请调整标题或图片后重试")
    return result


def _publish_data(
    *, title: str, description: str, images: list[dict[str, Any]], price: float,
    original_price: float | None, delivery: str, post_price: float,
    can_self_pickup: bool, category: dict[str, str],
) -> dict[str, Any]:
    post_fee: dict[str, Any] = {
        "canFreeShipping": False, "supportFreight": False, "onlyTakeSelf": False,
    }
    if delivery == "包邮":
        post_fee.update({"canFreeShipping": True, "supportFreight": True})
    elif delivery == "按距离计费":
        post_fee.update({"supportFreight": True, "templateId": "-100"})
    elif delivery == "一口价":
        post_fee.update({
            "supportFreight": True,
            "postPriceInCent": str(round(post_price * 100)),
            "templateId": "0",
        })
    else:
        post_fee["templateId"] = "0"
    price_dto = {"priceInCent": str(round(price * 100))}
    if original_price and original_price > 0:
        price_dto["origPriceInCent"] = str(round(original_price * 100))
    return {
        "freebies": False,
        "itemTypeStr": "b",
        "quantity": "1",
        "simpleItem": "true",
        "imageInfoDOList": [_image_info(image) for image in images],
        "itemTextDTO": {"desc": description, "title": title, "titleDescSeparate": True},
        "itemLabelExtList": [],
        "itemPriceDTO": price_dto,
        "userRightsProtocols": [{"enable": False, "serviceCode": "SKILL_PLAY_NO_MIND"}],
        "itemPostFeeDTO": post_fee,
        "itemAddrDTO": {},
        "defaultPrice": False,
        "itemCatDTO": {
            "catId": category["cat_id"],
            "catName": category["cat_name"],
            "channelCatId": category["channel_cat_id"],
            "tbCatId": category["tb_cat_id"],
        },
        "onlyTakeSelf": can_self_pickup,
        "uniqueCode": str(time.time_ns()),
        "sourceId": "pcMainPublish",
        "bizcode": "pcMainPublish",
        "publishScene": "pcMainPublish",
    }


async def publish_product(
    *, session: WebSession, title: str, description: str, images: list[PublishImage],
    price: float, original_price: float | None, delivery: str, post_price: float,
    can_self_pickup: bool,
) -> dict[str, str]:
    try:
        uploaded = [await asyncio.to_thread(_upload_image, session, image) for image in images]
        category = await asyncio.to_thread(_recommend_category, session, title, uploaded)
        payload = _publish_data(
            title=title, description=description, images=uploaded, price=price,
            original_price=original_price, delivery=delivery, post_price=post_price,
            can_self_pickup=can_self_pickup, category=category,
        )
        try:
            raw = await asyncio.to_thread(mtop_call, session, PUBLISH_API, payload, "1.0")
        except requests.RequestException as exc:
            raise PublishOutcomeUnknown(
                "发布请求超时，商品可能已经发布；请先到闲鱼或同步商品确认，不要重复提交"
            ) from exc
        item_id = str((raw.get("data") or {}).get("itemId") or "").strip()
        if not item_id:
            raise PublishOutcomeUnknown(
                "闲鱼已响应但没有返回商品 ID，发布结果需要人工确认"
            )
        return {
            "external_product_id": item_id,
            "category": category["cat_name"],
            "image_url": uploaded[0]["url"],
        }
    finally:
        session.http.close()
