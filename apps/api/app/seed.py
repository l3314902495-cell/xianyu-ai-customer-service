import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    AIProviderConfig,
    Conversation,
    ConversationStatus,
    Message,
    Product,
    ProductFAQ,
    ProductKnowledge,
    PromptTemplate,
    SenderType,
    SystemSetting,
    User,
    XianyuAccount,
)
from app.security import hash_password


async def seed() -> None:
    async with SessionLocal() as db:
        if await db.scalar(select(User).limit(1)):
            print("Seed already applied")
            return
        admin = User(username="admin", email="admin@example.com", password_hash=hash_password("Admin123!"))
        account = XianyuAccount(nickname="小鱼二手好物", external_account_id="mock-account-001", status="CONNECTED", adapter_type="mock", ai_enabled=True, last_connected_at=datetime.now(UTC))
        second_account = XianyuAccount(nickname="影音闲置小店", external_account_id="mock-account-002", status="CONNECTED", adapter_type="mock", ai_enabled=True, last_connected_at=datetime.now(UTC))
        db.add_all([admin, account, second_account]); await db.flush()
        mac = Product(account_id=account.id, external_product_id="XY-MAC-001", name="二手 MacBook Pro 14 英寸", category="数码电脑", price=7299, ai_prompt="回答配置问题要专业直接；询问成色时必须明确已有瑕疵，不使用夸张语言。", details={"型号":"MacBook Pro 14 M2 Pro","颜色":"深空灰","成色":"95新，A面有一处轻微划痕","配件":"原装充电器、包装盒","发货时间":"付款后24小时内"})
        buds = Product(account_id=account.id, external_product_id="XY-EAR-002", name="蓝牙降噪耳机", category="数码配件", price=399, ai_prompt="兼容性只根据知识回答；未列出的设备必须转人工确认。", details={"型号":"SoundAir Pro","颜色":"白色","成色":"九成新"})
        coat = Product(account_id=account.id, external_product_id="XY-COAT-003", name="羊毛双面呢大衣", category="女装", price=459, ai_prompt="尺码问题要客观，不能保证上身效果；提醒买家核对实测尺寸。", details={"颜色":"驼色","规格":"M码","成色":"仅试穿"})
        db.add_all([mac, buds, coat]); await db.flush()
        db.add_all([
            ProductKnowledge(product_id=mac.id,title="电池健康",content="电池健康度98%，循环次数42次",category="parameter",priority=10),
            ProductKnowledge(product_id=mac.id,title="购买时间",content="2025年11月购买",category="other"),
            ProductKnowledge(product_id=mac.id,title="瑕疵",content="A面右下角有一处约3毫米轻微划痕，不影响使用",category="condition"),
            ProductFAQ(product_id=mac.id,question="还在保修吗？",answer="Apple 有限保修到 2026年11月。",keywords=["保修","AppleCare"],priority=10),
            ProductKnowledge(product_id=buds.id,title="续航",content="耳机单次约6小时，配合充电盒约24小时",category="parameter"),
            ProductKnowledge(product_id=buds.id,title="兼容设备",content="支持 iPhone、安卓手机和 Windows 电脑的标准蓝牙连接",category="compatibility",priority=10),
            ProductFAQ(product_id=buds.id,question="苹果手机能用吗？",answer="可以，支持 iPhone 正常蓝牙连接和通话。",keywords=["苹果","iPhone"],priority=10),
            ProductKnowledge(product_id=coat.id,title="实测尺寸",content="肩宽39cm，胸围104cm，衣长108cm，手工测量误差约1-2cm",category="parameter",priority=10),
            ProductKnowledge(product_id=coat.id,title="材质",content="面料成分为90%羊毛、10%羊绒",category="parameter"),
            ProductFAQ(product_id=coat.id,question="有瑕疵吗？",answer="仅试穿，无污渍、起球或破损。",keywords=["瑕疵","成色"]),
        ])
        conversations = [
            Conversation(account_id=account.id,product_id=mac.id,external_conversation_id="seed-conv-1",buyer_id="buyer-1",buyer_nickname="数码爱好者",status=ConversationStatus.ACTIVE_AI,last_intent="product_condition",last_confidence=.94),
            Conversation(account_id=account.id,product_id=buds.id,external_conversation_id="seed-conv-2",buyer_id="buyer-2",buyer_nickname="阿青",status=ConversationStatus.NEEDS_HUMAN,needs_human=True,risk_level="MEDIUM"),
            Conversation(account_id=account.id,product_id=coat.id,external_conversation_id="seed-conv-3",buyer_id="buyer-3",buyer_nickname="小雨",status=ConversationStatus.ACTIVE_HUMAN,human_takeover=True,ai_enabled=False),
            Conversation(account_id=account.id,product_id=mac.id,external_conversation_id="seed-conv-4",buyer_id="buyer-4",buyer_nickname="Leo",status=ConversationStatus.CLOSED),
            Conversation(account_id=account.id,product_id=buds.id,external_conversation_id="seed-conv-5",buyer_id="buyer-5",buyer_nickname="白茶",status=ConversationStatus.ACTIVE_AI),
        ]
        db.add_all(conversations); await db.flush()
        db.add_all([
            Message(conversation_id=conversations[0].id,external_message_id="seed-msg-1",sender_type=SenderType.customer,content="电池怎么样？"),
            Message(conversation_id=conversations[0].id,reply_id="seed-reply-1",sender_type=SenderType.ai,content="电池健康度98%，循环42次。",sent=True),
            Message(conversation_id=conversations[1].id,external_message_id="seed-msg-2",sender_type=SenderType.customer,content="防水等级是 IPX7 吗？"),
            Message(conversation_id=conversations[2].id,external_message_id="seed-msg-3",sender_type=SenderType.customer,content="身高165穿会长吗？"),
            Message(conversation_id=conversations[2].id,reply_id="seed-human-1",sender_type=SenderType.human,content="衣长108cm，建议对照你常穿的大衣测量确认哦。",sent=True),
        ])
        db.add_all([
            PromptTemplate(name="全局客服成交策略",type="global",content="像真实卖家一样自然、简洁地回复，先解决买家顾虑，再柔和推动交易。精确商品事实不得编造；舒适度、保暖感、使用场景、搭配和选购建议等低风险体验问题，可以根据已知材质、参数和稳定常识给出明确判断，不要因为资料没有逐字描述体验就转人工。回复通常一至三句，避免模板腔和后台术语。",version="global-v1",enabled=True),
            AIProviderConfig(provider="mock",base_url="",api_key_encrypted="",model_name="mock-v1",temperature=.2,max_tokens=800,timeout=30,enabled=True),
            SystemSetting(key="global_ai_enabled",value={"enabled":True}),
        ])
        await db.commit(); print("Seed completed: admin / Admin123!")


if __name__ == "__main__":
    asyncio.run(seed())
