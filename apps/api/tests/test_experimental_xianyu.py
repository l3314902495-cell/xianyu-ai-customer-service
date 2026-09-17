import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
import requests

from app.adapters.xianyu import ExperimentalWebXianyuAdapter, adapter_for_account
from app.models import SenderType, XianyuAccount
from app.secrets import decrypt_secret, encrypt_secret
from app.services import xianyu_sync
from app.services.xianyu_protocol import (
    WebSession,
    XianyuFlowControlled,
    extract_incoming_text,
    extract_push_messages,
    extract_read_receipt,
    heartbeat_loop,
    mtop_call,
)
from app.services.xianyu_runtime import (
    APPLICATION_STREAM_SILENCE_SECONDS,
    AccountConnection,
    XianyuRuntime,
    select_changed_conversation_items,
    xianyu_runtime,
)
from app.services.xianyu_sync import decode_history_message


def test_realtime_push_exposes_normalized_buyer_avatar():
    decoded = {
        "sessionId": "conversation-avatar",
        "operation": {
            "senderInfo": {
                "senderUserId": "buyer-avatar",
                "avatarUrl": "//example.com/realtime-avatar.png",
            },
            "content": {"contentType": 1, "text": {"text": "hello"}},
        },
    }

    incoming = extract_incoming_text(decoded)

    assert incoming is not None
    assert incoming["send_user_avatar"] == "https://example.com/realtime-avatar.png"


def test_nested_user_profile_response_yields_avatar(monkeypatch):
    monkeypatch.setattr(
        xianyu_sync,
        "mtop_call",
        lambda *_args, **_kwargs: {
            "data": {
                "displayName": "buyer",
                "module": {
                    "base": {
                        "user": {
                            "avatarUrl": "//example.com/nested-avatar.png",
                        }
                    }
                }
            }
        },
    )
    session = WebSession(requests.Session(), "seller", "seller", "device")

    profile = xianyu_sync.fetch_conversation_user_info(session, "conversation-1")

    assert profile == {
        "nickname": "buyer",
        "avatar": "https://example.com/nested-avatar.png",
    }


def test_experimental_adapter_is_selected_per_account():
    account = XianyuAccount(
        nickname="本人闲鱼",
        external_account_id="123456",
        adapter_type="experimental-web",
    )
    assert isinstance(adapter_for_account(account), ExperimentalWebXianyuAdapter)


def test_credentials_are_encrypted_at_rest():
    raw = json.dumps({"cookies": {"unb": "123", "cookie2": "secret-cookie"}})
    encrypted = encrypt_secret(raw)
    assert "secret-cookie" not in encrypted
    assert decrypt_secret(encrypted) == raw


def test_new_web_text_push_is_decoded():
    decoded = {
        "sessionId": "conversation-1",
        "operation": {
            "senderInfo": {"senderUserId": "buyer-1"},
            "sessionInfo": {"extensions": {"itemId": "item-1"}},
            "content": {
                "contentType": 101,
                "custom": {
                    "data": base64.b64encode(
                        json.dumps({"contentType": 1, "text": {"text": "这个还有吗？"}}).encode()
                    ).decode()
                },
                "reminder": {"reminderTitle": "测试买家"},
            },
        },
    }
    frame = {
        "body": {
            "syncPushPackage": {
                "data": [{"data": base64.b64encode(json.dumps(decoded).encode()).decode()}]
            }
        }
    }
    pushes = extract_push_messages(frame)
    incoming = extract_incoming_text(pushes[0])
    assert incoming == {
        "event": "message",
        "cid": "conversation-1",
        "content_type": 101,
        "send_user_id": "buyer-1",
        "send_user_name": "测试买家",
        "send_message": "这个还有吗？",
    }


def test_direct_and_json_wrapped_pushes_are_decoded():
    decoded = {
        "sessionId": "conversation-2",
        "operation": {
            "senderInfo": {"senderUserId": "buyer-2"},
            "content": {"contentType": 1, "text": {"text": "实时消息"}},
        },
    }
    assert extract_push_messages(decoded) == [decoded]
    assert extract_push_messages({"body": [json.dumps(decoded)]}) == [decoded]
    assert extract_incoming_text(decoded)["send_message"] == "实时消息"


def test_xianyu_read_receipt_is_extracted_from_wrapped_sync_frame():
    decoded = {
        "1": ["4077151826249.PNM", "4066820235744.PNM"],
        "2": 2,
        "3": "conversation-read@goofish",
        "4": 1,
        "5": "1788926400000",
    }
    frame = {
        "body": {
            "syncPushPackage": {
                "data": [{"data": base64.b64encode(json.dumps(decoded).encode()).decode()}]
            }
        }
    }

    pushes = extract_push_messages(frame)

    assert pushes == [decoded]
    assert extract_read_receipt(pushes[0]) == {
        "cid": "conversation-read",
        "message_ids": ["4077151826249.PNM", "4066820235744.PNM"],
        "read": True,
        "timestamp": "1788926400000",
    }


def test_fallback_selects_changed_and_new_conversations_after_seed():
    signatures = {"same": "v1", "changed": "v1"}
    items = [
        ({"raw": "same"}, {"cid": "same", "last_message_signature": "v1"}),
        ({"raw": "changed"}, {"cid": "changed", "last_message_signature": "v2"}),
        ({"raw": "new"}, {"cid": "new", "last_message_signature": "v1"}),
    ]

    selected = select_changed_conversation_items(items, signatures, seeded=True)

    assert [parsed["cid"] for _, parsed in selected] == ["changed", "new"]
    assert signatures == {"same": "v1", "changed": "v2", "new": "v1"}


def test_fallback_first_index_is_bounded_to_newest_conversations():
    signatures: dict[str, str] = {}
    items = [
        ({"raw": index}, {"cid": f"c-{index}", "last_message_signature": f"v-{index}"})
        for index in range(10)
    ]

    selected = select_changed_conversation_items(items, signatures, seeded=False, limit=3)

    assert [parsed["cid"] for _, parsed in selected] == ["c-0", "c-1", "c-2"]
    assert len(signatures) == 10


def test_platform_reminder_is_marked_and_never_treated_as_buyer_text():
    decoded = {
        "sessionId": "conversation-system",
        "operation": {
            "content": {
                "contentType": 26,
                "reminder": {
                    "reminderContent": "[我完成了评价]",
                    "reminderTitle": "闲鱼通知",
                },
            }
        },
    }
    incoming = extract_incoming_text(decoded)
    assert incoming is not None
    assert incoming["_platform_message"] is True
    assert incoming["send_message"] == "[我完成了评价]"


def test_platform_promotional_plain_text_is_marked_as_platform_message():
    decoded = {
        "sessionId": "conversation-system",
        "operation": {
            "senderInfo": {"senderUserId": "platform"},
            "content": {
                "contentType": 1,
                "text": {"text": "开通留资卡功能   建联更安全"},
            },
        },
    }
    incoming = extract_incoming_text(decoded)
    assert incoming is not None
    assert incoming["_platform_message"] is True


def test_same_keywords_from_real_buyer_are_not_marked_as_platform_message():
    decoded = {
        "sessionId": "conversation-buyer",
        "operation": {
            "senderInfo": {"senderUserId": "buyer-1"},
            "content": {
                "contentType": 1,
                "text": {"text": "买家已付款，什么时候发货？"},
            },
        },
    }
    incoming = extract_incoming_text(decoded)
    assert incoming is not None
    assert "_platform_message" not in incoming


def test_history_platform_reminder_is_classified_as_system():
    result = decode_history_message(
        {
            "message": {
                "messageId": "system-1",
                "extension": {
                    "senderUserId": "platform",
                    "reminderContent": "快给ta一个评价吧～",
                },
            }
        },
        "seller-1",
        "conversation-1",
    )
    assert result is not None
    assert result["sender_type"] == SenderType.system


def test_history_order_reminder_with_buyer_sender_is_still_system():
    result = decode_history_message(
        {
            "message": {
                "messageId": "order-reminder-1",
                "extension": {
                    "senderUserId": "buyer-1",
                    "reminderContent": "[我已付款，等待你发货]",
                },
            }
        },
        "seller-1",
        "conversation-1",
    )
    assert result is not None
    assert result["sender_type"] == SenderType.system


def test_bracketed_payment_card_with_buyer_sender_is_system():
    result = decode_history_message(
        {
            "message": {
                "messageId": "payment-card-1",
                "content": {"text": {"text": "[已付款，待发货]"}},
                "extension": {"senderUserId": "buyer-1"},
            }
        },
        "seller-1",
        "conversation-1",
    )
    assert result is not None
    assert result["sender_type"] == SenderType.system


def test_unbracketed_buyer_payment_question_remains_customer():
    result = decode_history_message(
        {
            "message": {
                "messageId": "buyer-payment-question-1",
                "content": {"text": {"text": "我已经付款了，什么时候发货？"}},
                "extension": {"senderUserId": "buyer-1"},
            }
        },
        "seller-1",
        "conversation-1",
    )
    assert result is not None
    assert result["sender_type"] == SenderType.customer


def test_history_seller_text_has_priority_over_reminder_shape():
    result = decode_history_message(
        {
            "message": {
                "messageId": "seller-echo-1",
                "extension": {
                    "senderUserId": "seller-1",
                    "reminderContent": "付款后我马上发货",
                },
            }
        },
        "seller-1",
        "conversation-1",
    )
    assert result is not None
    assert result["sender_type"] == SenderType.human


def test_history_nested_text_is_normalized():
    payload = base64.b64encode(
        json.dumps({"text": {"text": "不是字典字符串"}}).encode()
    ).decode()
    result = decode_history_message(
        {
            "message": {
                "messageId": "m-1",
                "createAt": 1_700_000_000_000,
                "content": {"custom": {"data": payload}},
                "extension": {"senderUserId": "buyer-1"},
            }
        },
        "seller-1",
        "conversation-1",
    )
    assert result is not None
    assert result["content"] == "不是字典字符串"


def connection_with_verified_at(value: datetime | None) -> AccountConnection:
    return AccountConnection(
        account_id="account",
        session=WebSession(
            http=requests.Session(),
            unb="seller",
            tracknick="seller",
            device_id="device",
        ),
        credential_last_verified_at=value,
    )


def test_startup_refreshes_only_stale_credentials():
    now = datetime.now(UTC)
    assert XianyuRuntime._startup_refresh_due(connection_with_verified_at(None))
    assert XianyuRuntime._startup_refresh_due(
        connection_with_verified_at(now - timedelta(hours=2))
    )
    assert not XianyuRuntime._startup_refresh_due(
        connection_with_verified_at(now - timedelta(minutes=5))
    )


def test_session_expired_gets_one_normal_refresh_attempt_then_requires_login():
    message = "FAIL_SYS_SESSION_EXPIRED::Session过期"
    assert XianyuRuntime._is_refreshable_login_error(message)
    assert XianyuRuntime._is_risk_error(message)
    assert XianyuRuntime._is_refreshable_login_error("FAIL_SYS_TOKEN_EXOIRED")


def test_mtop_flow_control_is_reported_as_a_retryable_platform_limit(monkeypatch):
    class Response:
        @staticmethod
        def json():
            return {"ret": ["FAIL_SYS_FLOW_CONTROL::The request has been flow controlled"]}

    http = requests.Session()
    http.cookies.set("_m_h5_tk", "token_123", domain=".goofish.com")
    monkeypatch.setattr(http, "post", lambda *_args, **_kwargs: Response())
    session = WebSession(http=http, unb="seller", tracknick="seller", device_id="device")

    with pytest.raises(XianyuFlowControlled, match="等待约 60 秒"):
        mtop_call(session, "test.api", {"page": 1})


async def test_manual_sync_translates_flow_control_to_a_clear_retry_response(
    api_client, db, monkeypatch
):
    account = db.info["account"]
    account.adapter_type = "experimental-web"
    await db.commit()

    async def flow_controlled(_account_id: str):
        raise XianyuFlowControlled("The request has been flow controlled")

    monkeypatch.setattr(xianyu_runtime, "sync_account_data", flow_controlled)
    response = await api_client.post(f"/api/xianyu/accounts/{account.id}/sync")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert "等待约 60 秒" in response.json()["detail"]
    await db.refresh(account)
    assert "现有商品和会话不会丢失" in (account.last_error or "")


async def test_manual_sync_can_return_partial_success_when_only_history_is_limited(
    api_client, db, monkeypatch
):
    account = db.info["account"]
    account.adapter_type = "experimental-web"
    account.last_error = "old flow-control error"
    await db.commit()

    async def partial_sync(_account_id: str):
        return {
            "products_updated": 4,
            "conversation_sync_deferred": 1,
            "warning": "商品已同步；会话历史稍后低频补拉。",
        }

    monkeypatch.setattr(xianyu_runtime, "sync_account_data", partial_sync)
    response = await api_client.post(f"/api/xianyu/accounts/{account.id}/sync")

    assert response.status_code == 200
    assert response.json()["products_updated"] == 4
    assert response.json()["conversation_sync_deferred"] == 1
    assert "稍后低频补拉" in response.json()["warning"]
    await db.refresh(account)
    assert account.last_error is None


async def test_application_heartbeat_failure_is_visible_to_the_watchdog():
    class BrokenWebSocket:
        async def send(self, _payload: str):
            raise ConnectionError("socket is gone")

    with pytest.raises(ConnectionError, match="socket is gone"):
        await heartbeat_loop(BrokenWebSocket(), interval=0)


def test_quiet_account_does_not_force_reconnect_every_ninety_seconds():
    assert APPLICATION_STREAM_SILENCE_SECONDS >= 10 * 60
