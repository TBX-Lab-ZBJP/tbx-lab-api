import json
import base64
import hashlib
import hmac
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
DB_DIR = ROOT / "db"
DB_PATH = DB_DIR / "tbx_lab_xhs.sqlite3"
AUTH_SECRET = os.getenv("AUTH_SECRET", "tbx-lab-dev-secret")

HUNYUAN_BASE_URL = "https://tokenhub.tencentmaas.com/v1"
HUNYUAN_MODEL = "hunyuan-2.0-instruct-20251111"

TAG_BANNED_WORDS = ["最", "第一", "独家", "官方", "保证", "绝对", "唯一", "美团", "大众点评", "抖音", "飞猪", "携程", "去哪儿"]

PUBLISH_TIMING_RULES = {
    "餐饮_午餐": {
        "weekday": "周二/三 10:30-11:30",
        "weekend": "周六 10:00-11:00",
        "reason": "餐饮午餐导向，用户在准备午饭决策时刷小红书最活跃",
    },
    "餐饮_晚餐": {
        "weekday": "周四/五 17:00-18:30",
        "weekend": "周六 16:30-18:00",
        "reason": "晚餐决策窗口期",
    },
    "餐饮_宵夜": {
        "weekday": "周四/五 20:30-22:00",
        "weekend": "周六 21:00-23:00",
        "reason": "宵夜场景用户晚间活跃",
    },
    "酒旅_家庭": {
        "weekday": "周二/三 20:00-22:00",
        "weekend": "周日 19:00-21:00",
        "reason": "用户在规划周末出行时段最活跃",
    },
    "酒旅_情侣": {
        "weekday": "周四 20:00-22:00",
        "weekend": "周日 20:00-22:00",
        "reason": "周末出行决策窗口",
    },
    "default": {
        "weekday": "周二/三 20:00-22:00",
        "weekend": "周日 20:00-22:00",
        "reason": "晚间是小红书用户活跃高峰",
    },
}

PRIVATE_MESSAGE_TEMPLATES = {
    "餐饮": [
        {"question": "营业时间？", "template": "我们 {business_hours} 营业，最后入座提前半小时哦"},
        {"question": "在哪？/位置？", "template": "我们在 {address}，附近有公共停车场"},
        {"question": "人均多少？", "template": "一般人均 {avg_price}，多人去点招牌套餐性价比最高"},
        {"question": "需要预约吗？", "template": "周末建议提前 1 天预约，工作日直接来即可"},
        {"question": "有团购吗？", "template": "常用团购平台都能搜到我们店名"},
        {"question": "停车方便吗？", "template": "周边有公共停车场，周末建议早点来"},
        {"question": "新客有优惠吗？", "template": "进群可以领新人券，扫桌面二维码即可"},
        {"question": "适合带小孩/老人？", "template": "有儿童椅，菜品可备少辣或清淡口味"},
    ],
    "酒旅": [
        {"question": "怎么预订？", "template": "可以直接私信选房型，我们帮您锁定"},
        {"question": "位置？", "template": "我们在 {address}，距离 {district} 商圈步行 X 分钟"},
        {"question": "房价？", "template": "平日 X 元起，周末/节假日略有上浮"},
        {"question": "可以提前入住吗？", "template": "标准入住 15:00 起，可提前联系，按当天排房情况安排"},
        {"question": "退房时间？", "template": "标准退房 12:00 前，需要延迟可提前 1 小时跟前台说"},
        {"question": "停车？", "template": "酒店配套停车场，含在房价内"},
        {"question": "有早餐吗？", "template": "含中式自助早餐，07:30-10:00 供应"},
        {"question": "周边游玩？", "template": "前台有手绘地图，可推荐附近 1km 内的景点和小馆"},
    ],
    "default": [
        {"question": "营业时间？", "template": "我们 {business_hours} 营业"},
        {"question": "位置？", "template": "我们在 {address}"},
        {"question": "怎么预约？", "template": "私信留下时间和人数即可"},
    ],
}

DEFAULT_PLANS = [
    {
        "code": "free",
        "name": "免费试用",
        "price_cents": 0,
        "duration_days": 3,
        "quota": 5,
        "features": ["3 天体验", "5 次生成额度", "基础素材包"],
        "is_recommended": 0,
    },
    {
        "code": "monthly",
        "name": "月卡",
        "price_cents": 9900,
        "duration_days": 30,
        "quota": 50,
        "features": ["30 天有效", "50 次生成额度", "完整素材包"],
        "is_recommended": 0,
    },
    {
        "code": "quarterly",
        "name": "季卡",
        "price_cents": 25800,
        "duration_days": 90,
        "quota": 200,
        "features": ["90 天有效", "200 次生成额度", "适合稳定运营"],
        "is_recommended": 0,
    },
    {
        "code": "yearly",
        "name": "年卡",
        "price_cents": 88800,
        "duration_days": 365,
        "quota": 1000,
        "features": ["365 天有效", "1000 次生成额度", "推荐长期使用"],
        "is_recommended": 1,
    },
]

RED_LINES = [
    "字节",
    "官方服务商",
    "官方营销服务商",
    "威海特别想文化传媒有限公司",
    "保证GMV",
    "保证ROI",
    "全网最低",
    "第一",
    "唯一",
    "扫码",
    "微信号",
    "加我微信",
    "¥998",
    "¥2,980",
    "2980",
    # —— 他平台引流红线（小红书禁忌：明确指引到其他平台会限流/屏蔽）——
    "美团",
    "大众点评",
    "抖音团购",
    "飞猪",
    "携程",
    "去哪儿",
    "可在美团",
    "可在大众点评",
    "美团搜",
    "大众点评搜",
]

REFERENCE_TOPICS = {
    "酒旅": [
        {"title": "威海这家海景房，窗边坐一下午都不想走", "style": "真实体验日记", "direction": "窗景 · 氛围"},
        {"title": "七夕住这里也太会了吧，晚上看海好舒服", "style": "情侣出行", "direction": "节日 · 预约"},
        {"title": "来威海前先看这篇，民宿真的别乱订", "style": "避坑提醒", "direction": "差评避坑"},
        {"title": "这间房最戳我的不是海景，是晚上真的很安静", "style": "细节体验", "direction": "睡眠体验"},
        {"title": "周末想放空的话，这种房间真的很适合", "style": "收藏清单", "direction": "周末 · 放松"},
        {"title": "带爸妈来威海，我会优先看这几个点", "style": "亲子家庭", "direction": "适合人群"},
        {"title": "同样看海，为什么有些房间住起来更舒服", "style": "对比选择", "direction": "房型对比"},
        {"title": "第一次来这边，位置比装修更重要", "style": "路线攻略", "direction": "位置 · 交通"},
    ],
    "餐饮": [
        {"title": "这家真的可以二刷，招牌菜闭眼点", "style": "真实体验日记", "direction": "招牌菜"},
        {"title": "姐妹们这家我先替你们吃了，真的香", "style": "种草分享", "direction": "菜品种草"},
        {"title": "人均不高但吃得很满足，适合周末约饭", "style": "性价比", "direction": "客单价"},
        {"title": "第一次来别乱点，这几个更稳", "style": "点单攻略", "direction": "隐藏菜单"},
        {"title": "这家排队前先看一眼，少踩坑", "style": "避坑提醒", "direction": "排队 · 规则"},
        {"title": "适合朋友小聚的一家，氛围比想象中舒服", "style": "场景推荐", "direction": "聚餐"},
        {"title": "这口热乎的真的很治愈，下次还来", "style": "情绪种草", "direction": "口味体验"},
        {"title": "同价位怎么选，我会优先看这几样", "style": "对比选择", "direction": "套餐对比"},
    ],
}

app = FastAPI(title="TBX Lab XHS Publisher", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def db_connect() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_ts() -> int:
    return int(time.time())


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def init_db() -> None:
    with db_connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            phone TEXT NOT NULL UNIQUE,
            nickname TEXT NOT NULL,
            plan_code TEXT NOT NULL DEFAULT 'free',
            quota_remaining INTEGER NOT NULL DEFAULT 5,
            trial_started_at INTEGER NOT NULL,
            trial_expires_at INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plans (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price_cents INTEGER NOT NULL,
            duration_days INTEGER NOT NULL,
            quota INTEGER NOT NULL,
            features_json TEXT NOT NULL,
            is_recommended INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS usage_logs (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            quota_before INTEGER NOT NULL,
            quota_after INTEGER NOT NULL,
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS merchant_profiles (
            user_id TEXT PRIMARY KEY,
            profile_json TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS drafts (
            user_id TEXT PRIMARY KEY,
            draft_json TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS histories (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            history_json TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        """)
        for plan in DEFAULT_PLANS:
            conn.execute(
                """
                INSERT INTO plans (code, name, price_cents, duration_days, quota, features_json, is_recommended)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name=excluded.name,
                    price_cents=excluded.price_cents,
                    duration_days=excluded.duration_days,
                    quota=excluded.quota,
                    features_json=excluded.features_json,
                    is_recommended=excluded.is_recommended
                """,
                (
                    plan["code"],
                    plan["name"],
                    plan["price_cents"],
                    plan["duration_days"],
                    plan["quota"],
                    json.dumps(plan["features"], ensure_ascii=False),
                    plan["is_recommended"],
                ),
            )


@app.on_event("startup")
def startup() -> None:
    init_db()


class HotTitleRequest(BaseModel):
    platform: str = "小红书"
    lane: str = "餐饮"
    keyword: str = ""
    merchant_profile: dict[str, Any] | None = None


class DraftRequest(BaseModel):
    title: str
    selected_title: str = ""
    hook_type: str = ""
    style: str = "style_warm"
    outputType: str = "标准笔记素材包"
    noteShape: str = "标准笔记素材包"
    framework: str = "避坑警告"
    lane: str = ""
    keyword: str = ""
    material: str = ""
    merchant_profile: dict[str, Any] | None = None


class ScanRequest(BaseModel):
    text: str = ""
    content_long: str = ""
    content_short: str = ""
    tags_traffic: list[str] = []
    tags_precise: list[str] = []
    tags_longtail: list[str] = []
    engagement_comments: list[Any] = []


class SendCodeRequest(BaseModel):
    phone: str


class LoginRequest(BaseModel):
    phone: str
    code: str


class SyncStateRequest(BaseModel):
    merchant_profile: dict[str, Any] | None = None
    draft: dict[str, Any] | None = None
    history: list[Any] | None = None


class SaveMerchantProfileRequest(BaseModel):
    profile: dict[str, Any]


class SaveDraftRequest(BaseModel):
    draft: dict[str, Any]


class SaveHistoryRequest(BaseModel):
    history: list[Any]


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def create_token(user_id: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": user_id, "exp": now_ts() + 60 * 60 * 24 * 30}
    signing_input = ".".join([
        b64url_encode(json.dumps(header, separators=(",", ":")).encode()),
        b64url_encode(json.dumps(payload, separators=(",", ":")).encode()),
    ])
    signature = hmac.new(AUTH_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{b64url_encode(signature)}"


def verify_token(token: str) -> str:
    try:
        signing_input, signature = token.rsplit(".", 1)
        expected = b64url_encode(hmac.new(AUTH_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        payload = json.loads(b64url_decode(signing_input.split(".")[1]))
        if int(payload.get("exp") or 0) < now_ts():
            raise ValueError("expired")
        return str(payload["sub"])
    except Exception as exc:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录") from exc


def current_user(authorization: str | None) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    user_id = verify_token(authorization.replace("Bearer ", "", 1).strip())
    with db_connect() as conn:
        user = row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在，请重新登录")
    return user


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "phone": user["phone"],
        "nickname": user["nickname"],
        "plan_code": user["plan_code"],
        "quota_remaining": user["quota_remaining"],
        "trial_expires_at": user["trial_expires_at"],
    }


def load_plans() -> list[dict[str, Any]]:
    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM plans ORDER BY price_cents ASC").fetchall()
    return [
        {
            "code": row["code"],
            "name": row["name"],
            "price_cents": row["price_cents"],
            "price": row["price_cents"] // 100,
            "duration_days": row["duration_days"],
            "quota": row["quota"],
            "features": json.loads(row["features_json"]),
            "is_recommended": bool(row["is_recommended"]),
        }
        for row in rows
    ]


def merchant_profile_prompt(profile: dict[str, Any] | None) -> str:
    if not isinstance(profile, dict) or not profile:
        return "【商家信息】未提供，请使用本地生活商家的通用口径生成。"

    def clean(value: Any) -> str:
        if isinstance(value, list):
            return "、".join(str(item).strip() for item in value if str(item).strip())
        return str(value or "").strip()

    return f"""
【商家信息】（如未提供则使用默认值）
- 店名：{clean(profile.get("store_name")) or "未提供"}
- 品类：{clean(profile.get("category")) or "未提供"}
- 城市/商圈：{clean(profile.get("city"))} {clean(profile.get("district"))}
- 人均：{clean(profile.get("avg_price")) or "未提供"} 元
- 招牌产品：{clean(profile.get("signature_items")) or "未提供"}
- 卖点：{clean(profile.get("selling_points")) or "未提供"}

请基于以上商家信息进行个性化生成，将店名、产品名、地点等真实信息融入选题和文案中。
""".strip()


@app.get("/")
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "tbx-lab-xhs"}


@app.post("/api/v1/auth/send-code")
def send_code(payload: SendCodeRequest) -> dict[str, Any]:
    # 开发期固定验证码；上线前替换为真实短信服务。
    phone = re.sub(r"\D", "", payload.phone or "")
    if len(phone) < 6:
        raise HTTPException(status_code=400, detail="请输入正确手机号")
    return {"sent": True, "dev_code": "1234"}


@app.post("/api/v1/auth/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    phone = re.sub(r"\D", "", payload.phone or "")
    if len(phone) < 6:
        raise HTTPException(status_code=400, detail="请输入正确手机号")
    if payload.code != "1234":
        raise HTTPException(status_code=400, detail="验证码错误")
    created = now_ts()
    with db_connect() as conn:
        user = row_to_dict(conn.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone())
        if not user:
            user_id = str(uuid.uuid4())
            nickname = f"用户{phone[-4:]}"
            conn.execute(
                """
                INSERT INTO users (id, phone, nickname, plan_code, quota_remaining, trial_started_at, trial_expires_at, created_at, updated_at)
                VALUES (?, ?, ?, 'free', 5, ?, ?, ?, ?)
                """,
                (user_id, phone, nickname, created, created + 3 * 24 * 3600, created, created),
            )
            user = row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
    return {"token": create_token(user["id"]), "user": public_user(user), "plans": load_plans()}


@app.get("/api/v1/auth/me")
def me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    return {"user": public_user(user), "plans": load_plans()}


@app.get("/api/v1/plans")
def plans() -> dict[str, Any]:
    return {"plans": load_plans()}


@app.get("/api/v1/user/state")
def get_user_state(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    with db_connect() as conn:
        profile_row = conn.execute("SELECT profile_json FROM merchant_profiles WHERE user_id = ?", (user["id"],)).fetchone()
        draft_row = conn.execute("SELECT draft_json FROM drafts WHERE user_id = ?", (user["id"],)).fetchone()
        history_rows = conn.execute("SELECT history_json FROM histories WHERE user_id = ? ORDER BY created_at ASC LIMIT 10", (user["id"],)).fetchall()
    return {
        "merchant_profile": json.loads(profile_row["profile_json"]) if profile_row else None,
        "draft": json.loads(draft_row["draft_json"]) if draft_row else None,
        "history": [json.loads(row["history_json"]) for row in history_rows],
    }


@app.post("/api/v1/user/sync")
def sync_user_state(payload: SyncStateRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    stamp = now_ts()
    with db_connect() as conn:
        if isinstance(payload.merchant_profile, dict) and payload.merchant_profile:
            conn.execute(
                "INSERT INTO merchant_profiles (user_id, profile_json, updated_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET profile_json=excluded.profile_json, updated_at=excluded.updated_at",
                (user["id"], json.dumps(payload.merchant_profile, ensure_ascii=False), stamp),
            )
        if isinstance(payload.draft, dict) and payload.draft:
            conn.execute(
                "INSERT INTO drafts (user_id, draft_json, updated_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET draft_json=excluded.draft_json, updated_at=excluded.updated_at",
                (user["id"], json.dumps(payload.draft, ensure_ascii=False), stamp),
            )
        if isinstance(payload.history, list):
            conn.execute("DELETE FROM histories WHERE user_id = ?", (user["id"],))
            for item in payload.history[-10:]:
                if isinstance(item, dict):
                    conn.execute(
                        "INSERT INTO histories (id, user_id, history_json, created_at) VALUES (?, ?, ?, ?)",
                        (str(item.get("id") or uuid.uuid4()), user["id"], json.dumps(item, ensure_ascii=False), stamp),
                    )
    return get_user_state(authorization)


@app.post("/api/v1/user/merchant-profile")
def save_cloud_merchant_profile(payload: SaveMerchantProfileRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO merchant_profiles (user_id, profile_json, updated_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET profile_json=excluded.profile_json, updated_at=excluded.updated_at",
            (user["id"], json.dumps(payload.profile, ensure_ascii=False), now_ts()),
        )
    return {"ok": True}


@app.post("/api/v1/user/draft")
def save_cloud_draft(payload: SaveDraftRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO drafts (user_id, draft_json, updated_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET draft_json=excluded.draft_json, updated_at=excluded.updated_at",
            (user["id"], json.dumps(payload.draft, ensure_ascii=False), now_ts()),
        )
    return {"ok": True}


@app.post("/api/v1/user/history")
def save_cloud_history(payload: SaveHistoryRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    stamp = now_ts()
    with db_connect() as conn:
        conn.execute("DELETE FROM histories WHERE user_id = ?", (user["id"],))
        for item in payload.history[-10:]:
            if isinstance(item, dict):
                conn.execute(
                    "INSERT INTO histories (id, user_id, history_json, created_at) VALUES (?, ?, ?, ?)",
                    (str(item.get("id") or uuid.uuid4()), user["id"], json.dumps(item, ensure_ascii=False), stamp),
                )
    return {"ok": True}


@app.get("/api/v1/xhs/model-test")
async def model_test() -> dict[str, Any]:
    api_key = os.getenv("HUNYUAN_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="HUNYUAN_API_KEY 未配置")
    try:
        result = await generate_with_hunyuan({
            "title": "模型连通性测试",
            "material": "请只返回一条很短的小红书测试文案。",
            "lane": "餐饮",
        })
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"混元调用失败：{exc}") from exc
    return {
        "status": "ok",
        "provider": os.getenv("LLM_PROVIDER", "hunyuan"),
        "model": os.getenv("HUNYUAN_MODEL", HUNYUAN_MODEL),
        "sample_title": result.get("title", ""),
    }


@app.get("/api/v1/xhs/env-check")
def env_check() -> dict[str, Any]:
    api_key = os.getenv("HUNYUAN_API_KEY", "").strip()
    return {
        "provider": os.getenv("LLM_PROVIDER", "hunyuan"),
        "has_hunyuan_api_key": bool(api_key),
        "hunyuan_api_key_prefix": api_key[:6] + "***" if api_key else "",
        "hunyuan_model": os.getenv("HUNYUAN_MODEL", HUNYUAN_MODEL),
        "hunyuan_base_url": os.getenv("HUNYUAN_BASE_URL", HUNYUAN_BASE_URL),
        "allow_local_fallback": os.getenv("ALLOW_LOCAL_FALLBACK", "1"),
    }


@app.post("/api/v1/xhs/hot-titles")
async def hot_titles(payload: HotTitleRequest) -> dict[str, Any]:
    try:
        return await generate_hot_titles_with_hunyuan(payload)
    except Exception:
        if os.getenv("ALLOW_LOCAL_FALLBACK", "1") == "0":
            raise
        return fallback_hot_titles(payload)


async def generate_hot_titles_with_hunyuan(payload: HotTitleRequest) -> dict[str, Any]:
    # 说明：当前数据来源为基于硬编码参考池的 LLM 改写，
    # 不是真实小红书实时数据。产品文案已统一改为"参考"口径，
    # 真实数据接入后再升级此处。
    lane = payload.lane.strip() if payload.lane.strip() in REFERENCE_TOPICS else "餐饮"
    keyword = payload.keyword.strip() or ("新品种草 客单价对比 隐藏菜单" if lane == "餐饮" else "周末亲子房 海边民宿 节日套餐")
    reference_pool = REFERENCE_TOPICS[lane]
    prompt = """
你是本地生活小红书转化型选题策划。目标用户是餐饮/酒旅老板，目标不是泛流量，而是让顾客收藏、咨询、团购点击、预约、核销、到店。
请基于用户输入的行业、关键词，以及提供的行业爆款标题参考，生成 30 个“小红书本地生活爆款选题参考”。
注意：这不是实时抓取小红书榜单，不要声称“真实实时数据”。你是在参考池基础上做二次改写。
如用户提供了商家信息，必须把店名、所在商圈、招牌产品、卖点融入选题中。
为每个改写选题，额外生成 3 个差异化标题变体：
variant_emotion（情绪型）：以强情绪词开头，如绝绝子、谁懂啊、姐妹们救命、终于找到、爱了爱了。
variant_number（数字型）：以具体数字开头，如人均XX、3 个理由、1 次想来 5 次、藏了 3 年。
variant_suspense（悬念型）：以反差/疑问开头，如藏了 N 年没敢推荐、老板不让说、本来不想分享但。
规则：三条均 ≤ 22 字；不与原标题、变体相互重复；必须融入商家档案的店名/品类/地段元素；禁用词：最、第一、最低、独家、保证、官方、绝对、唯一。
必须输出严格 JSON：
{
  "items": [
    {"id":"hot_1","title":"...","type":"种草","hook_type":"情绪","variants":{"emotion":"...","number":"...","suspense":"..."},"platform":"小红书","heat":88,"direction":"新品种草 · 季节","source_style":"真实体验日记"}
  ]
}
标题要像真实运营写的，不要夸大承诺，不要写保证爆单。只输出 JSON。
""".strip()
    result = await generate_raw_json_with_hunyuan(prompt, {
        "lane": lane,
        "keyword": keyword,
        "platform": payload.platform,
        "reference_pool": reference_pool,
        "merchant_profile": payload.merchant_profile,
        "merchant_profile_text": merchant_profile_prompt(payload.merchant_profile),
    })
    items = result.get("items", [])
    if not isinstance(items, list) or not items:
        raise RuntimeError("模型没有返回有效选题")
    normalized = []
    for index, item in enumerate(items[:30]):
        title = str(item.get("title") or "").strip()
        normalized.append({
            "id": str(item.get("id") or f"hot_{index + 1}"),
            "title": title,
            "type": str(item.get("type") or "种草"),
            "hook_type": str(item.get("hook_type") or "情绪"),
            "variants": normalize_variants(item.get("variants"), title, payload.merchant_profile, lane, index),
            "platform": str(item.get("platform") or payload.platform or "小红书"),
            "heat": int(item.get("heat") or (88 - index % 18)),
            "direction": str(item.get("direction") or "到店理由"),
            "source_style": str(item.get("source_style") or item.get("style") or reference_pool[index % len(reference_pool)]["style"]),
            "keyword": keyword,
        })
    return {"count": len(normalized), "items": normalized}


def fallback_hot_titles(payload: HotTitleRequest) -> dict[str, Any]:
    lane = payload.lane.strip() if payload.lane.strip() in REFERENCE_TOPICS else "餐饮"
    pool = REFERENCE_TOPICS[lane]
    modifiers = ["周末版", "七夕版", "避坑版", "收藏版", "第一次来版", "适合朋友版", "性价比版", "真实体验版"]
    platforms = [payload.platform or "小红书", "抖音"]
    keyword = payload.keyword.strip() or ("新品种草 客单价对比 隐藏菜单" if lane == "餐饮" else "周末亲子房 海边民宿 节日套餐")
    profile = payload.merchant_profile or {}
    store_name = str(profile.get("store_name") or "").strip()
    signature_items = profile.get("signature_items") if isinstance(profile.get("signature_items"), list) else []
    signature = str(signature_items[0]).strip() if signature_items else ""
    items = []
    for index in range(30):
        base = pool[index % len(pool)]
        title = base["title"]
        if keyword and index % 3 == 0:
            title = f"{keyword.split()[0]}｜{title}"
        if store_name and index % 5 == 1:
            title = f"{store_name}怎么发：{title}"
        if signature and index % 5 == 2:
            title = f"{signature}种草角度：{title}"
        if index >= len(pool):
            title = f"{title}（{modifiers[index % len(modifiers)]}）"
        items.append({
            "id": f"hot_{index + 1}",
            "title": title,
            "type": "种草" if index % 2 else "避坑",
            "hook_type": ["情绪", "数字", "悬念"][index % 3],
            "variants": normalize_variants({}, title, payload.merchant_profile, lane, index),
            "platform": platforms[index % len(platforms)],
            "heat": 72 + ((index * 7) % 27),
            "direction": base["direction"],
            "source_style": base["style"],
            "keyword": keyword,
        })
    return {"count": len(items), "items": items}


def normalize_variants(raw: Any, title: str, profile: dict[str, Any] | None, lane: str, index: int) -> dict[str, str]:
    variants = raw if isinstance(raw, dict) else {}
    generated = fallback_variants(title, profile, lane, index)
    anchor = variant_anchor(profile, lane)
    def pick(*keys: str) -> str:
        value = ""
        for key in keys:
            value = str(variants.get(key) or "").strip()
            if value:
                break
        if not value or (anchor and anchor not in value):
            value = generated[keys[0].replace("variant_", "")]
        return value[:22]
    return {
        "emotion": pick("emotion", "variant_emotion"),
        "number": pick("number", "variant_number"),
        "suspense": pick("suspense", "variant_suspense"),
    }


def fallback_variants(title: str, profile: dict[str, Any] | None, lane: str, index: int) -> dict[str, str]:
    anchor = variant_anchor(profile, lane)
    number_prefix = "人均80" if lane == "餐饮" else "3个理由"
    return {
        "emotion": f"谁懂啊 {anchor}真香",
        "number": f"{number_prefix}想冲{anchor}",
        "suspense": f"本来不想分享{anchor}",
    }


def variant_anchor(profile: dict[str, Any] | None, lane: str) -> str:
    profile = profile or {}
    store_name = str(profile.get("store_name") or "").strip()
    district = str(profile.get("district") or "").strip()
    signature_items = profile.get("signature_items") if isinstance(profile.get("signature_items"), list) else []
    signature = str(signature_items[0]).strip() if signature_items else ""
    return store_name or signature or district or lane


@app.post("/api/v1/xhs/scan")
def scan(payload: ScanRequest) -> dict[str, Any]:
    comment_text = " ".join(
        str(item.get("text") if isinstance(item, dict) else item or "").strip()
        for item in payload.engagement_comments
    )
    tag_text = " ".join(payload.tags_traffic + payload.tags_precise + payload.tags_longtail)
    if payload.content_long or payload.content_short or tag_text or comment_text:
        long_result = scan_text(payload.content_long)
        short_result = scan_text(payload.content_short)
        tag_result = scan_text(tag_text)
        comment_result = scan_text(comment_text)
        terms = list(dict.fromkeys(
            long_result["risk_terms"]
            + short_result["risk_terms"]
            + tag_result["risk_terms"]
            + comment_result["risk_terms"]
        ))
        return {
            "passed": long_result["passed"] and short_result["passed"] and tag_result["passed"] and comment_result["passed"],
            "risk_terms": terms,
            "score": min(long_result["score"], short_result["score"], tag_result["score"], comment_result["score"]),
            "suggestions": ["长短版、话题标签和评论区话术均需删除命中红线", "改成站内咨询或评论区承接"] if terms else ["长短版、话题标签和评论区话术均可进入素材产出前确认"],
            "long_result": long_result,
            "short_result": short_result,
            "tag_result": tag_result,
            "comment_result": comment_result,
        }
    return scan_text(payload.text)


@app.post("/api/v1/xhs/draft")
async def draft(payload: DraftRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(authorization)
    if int(user.get("quota_remaining") or 0) <= 0:
        raise HTTPException(status_code=403, detail="额度已用完，请升级套餐")
    try:
        result = await generate_with_hunyuan(payload.model_dump())
    except Exception as exc:
        if os.getenv("ALLOW_LOCAL_FALLBACK", "1") == "1":
            result = fallback_draft(payload)
            result["model_error"] = str(exc)
        else:
            raise HTTPException(status_code=502, detail=f"国内大模型调用失败：{exc}") from exc

    result = clean_generated_result(result, payload)
    result["title"] = result.get("title") or payload.title
    result["firstComment"] = result.get("firstComment") or result.get("first_comment") or "想要结构参考的朋友，评论扣「模板」。"
    tag_buckets = normalize_tag_buckets(result, payload)
    result.update(tag_buckets)
    result["tags"] = normalize_tags(tag_buckets["tags_traffic"] + tag_buckets["tags_precise"] + tag_buckets["tags_longtail"])
    result["photo_checklist"] = normalize_photo_checklist(result.get("photo_checklist"), payload)
    result["publish_timing"] = match_publish_timing(payload.merchant_profile, payload.selected_title or payload.title)
    result["engagement_comments"] = normalize_engagement_comments(result.get("engagement_comments"), payload)
    result["private_messages"] = render_private_messages(payload.merchant_profile)
    result["benchmark"] = result.get("benchmark") or fixed_benchmark()
    result["compliance"] = scan(ScanRequest(
        content_long=result.get("content_long", ""),
        content_short=result.get("content_short", ""),
        tags_traffic=result.get("tags_traffic", []),
        tags_precise=result.get("tags_precise", []),
        tags_longtail=result.get("tags_longtail", []),
        engagement_comments=result.get("engagement_comments", []),
    ))
    quota_before = int(user.get("quota_remaining") or 0)
    quota_after = quota_before - 1
    with db_connect() as conn:
        conn.execute(
            "UPDATE users SET quota_remaining = ?, updated_at = ? WHERE id = ?",
            (quota_after, now_ts(), user["id"]),
        )
        conn.execute(
            "INSERT INTO usage_logs (id, user_id, action, quota_before, quota_after, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                user["id"],
                "draft_generate",
                quota_before,
                quota_after,
                json.dumps({"title": payload.selected_title or payload.title, "style": payload.style}, ensure_ascii=False),
                now_ts(),
            ),
        )
    result["user"] = public_user({**user, "quota_remaining": quota_after})
    result["status"] = "employee_review_required"
    result["outputType"] = "标准笔记素材包"
    return result


async def generate_with_hunyuan(user_input: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("HUNYUAN_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 HUNYUAN_API_KEY")

    base_url = os.getenv("HUNYUAN_BASE_URL", HUNYUAN_BASE_URL).rstrip("/")
    model = os.getenv("HUNYUAN_MODEL", HUNYUAN_MODEL)
    style = str(user_input.get("style") or "style_warm")
    style_prompts = {
        "style_warm": "style_warm（亲切闺蜜型）：第一人称“我”、姐妹们、家人们；每段 1-2 个 emoji；多用感叹号和转折词；用词口语化，如绝了、真的爱、冲就完事、姐妹必去。",
        "style_pro": "style_pro（专业测评型）：第一人称“我/我们”；客观描述与主观感受 7:3；全篇 emoji ≤ 5 个；可用数据化表达，如面积、等位、人均；专业但不生硬。",
        "style_contrast": "style_contrast（反差爆点型）：强反差开头；每段制造 1 个反转；多用反问、设问；结尾留悬念引导评论。",
    }
    system_prompt = """
你是“特别想-Lab”的本地生活小红书带客素材包工具，第一批目标用户是餐饮和酒旅老板。
老板真正付费的不是内容工具，而是带客结果：收藏、咨询、团购点击、预约、核销、到店。
你要根据行业、爆款选题参考、店铺信息、菜品/房型/价格/位置/规则，生成可审核、可手动发布的小红书标准笔记素材包。
必须输出严格 JSON，不要 Markdown，不要代码块。字段：
title: 字符串
content_long: 字符串，长版文案 280-380 字，作为主笔记正文
content_short: 字符串，短版文案 100-150 字，用于评论区追加、私信发送、群发
tags: 字符串数组，8 到 12 个标签，不带 # 号
firstComment: 字符串
benchmark: 对标参考对象，包含 accounts、notes、usage
tags 字段升级为三类，请按以下规则分别输出：
- tags_traffic（流量型）：2-3 个大流量泛话题，如"探店""本地生活""美食推荐"
- tags_precise（精准型）：2-3 个品类+地域组合，如"{city}{category}""{district}美食"
- tags_longtail（长尾型）：1-2 个具体场景词，如"一人食""周末去哪儿""适合带娃"
- tags（兼容旧字段）：以上三类合并为单一数组
所有标签：不带 # 号；不超过 12 字符；不出现禁用词：最、第一、独家、官方、保证、绝对、唯一；不出现他平台名。
photo_checklist 字段：根据本篇选题类型和商家品类，生成拍照清单。
- items：5-9 张图清单，每张包含 order（序号 1-9）、subject（拍什么）、tip（拍摄角度/技巧，一句话）
- tips：3-5 条通用拍摄口诀
餐饮重点：门头、招牌菜、餐桌全景、就餐场景、菜单/价签。酒旅重点：门头、房型全景、床品/卫浴/早餐细节、风景/窗景、地段标识。
安全要求：
1. 不声称是字节、抖音、小红书官方或官方服务商。
2. 不承诺 GMV、ROI、爆单、第一、唯一、全网最低。
3. 不诱导扫码、加微信或站外私聊。
4. 不编造具体店名、地址、价格、成交数据。
5. 严禁出现"美团/大众点评/抖音团购/抖音/飞猪/携程/去哪儿"等具体他平台名（小红书会判定为站外引流并限流）。如需提及团购券，统一用模糊表达：如"团购券""常用团购平台""APP 搜店名"，不出现平台具体品牌名。
文案必须像真实用户发的小红书笔记，不要像广告、招商页或机构营销话术。
正文允许自然使用 5 到 10 个 emoji，但不要每句话都堆。
不要使用“实时榜单”“真实实时数据”口径，统一使用“爆款选题参考”“行业爆款标题”口径。
短版要求：保留长版的核心钩子和到店动作，删除铺垫和情绪渲染，适合作为评论区补充信息或私信发送。
""".strip()
    engagement_prompt = """
engagement_comments 字段：为本篇笔记生成 5-10 条评论区埋点话术，让商家用员工号/小号在评论区先发，引导真实用户互动。
按以下 3 类分配：type_question 提问引导型 2-3 条；type_answer 自答信息型 2-4 条；type_engage 情绪互动型 2-3 条。
输出结构示例："engagement_comments":[{"type":"type_question","text":"请问周末几点开门？想带家人去"}]
要求：每条 8-30 字；模拟不同口吻；不能出现禁用词；不能直接复制文案原句；不能提及具体他平台名（美团/大众点评/抖音团购等）。
""".strip()
    system_prompt = f"{system_prompt}\n\n{engagement_prompt}\n\n【当前文案风格】\n{style_prompts.get(style, style_prompts['style_warm'])}\n\n{merchant_profile_prompt(user_input.get('merchant_profile'))}"
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_input, ensure_ascii=False)},
        ],
        "temperature": 0.45,
    }
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=request_body,
        )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return parse_json(content)


async def generate_raw_json_with_hunyuan(system_prompt: str, user_input: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("HUNYUAN_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 HUNYUAN_API_KEY")
    base_url = os.getenv("HUNYUAN_BASE_URL", HUNYUAN_BASE_URL).rstrip("/")
    model = os.getenv("HUNYUAN_MODEL", HUNYUAN_MODEL)
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_input, ensure_ascii=False)},
        ],
        "temperature": 0.35,
    }
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=request_body,
        )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return parse_json(content)


def parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if match:
            return json.loads(match.group(0))
        raise


def scan_text(text: str) -> dict[str, Any]:
    hits = [word for word in RED_LINES if word in text]
    return {
        "passed": len(hits) == 0,
        "risk_terms": hits,
        "score": max(0, 100 - len(hits) * 15),
        "suggestions": ["删除命中红线", "改成站内咨询或评论区关键词"] if hits else ["可进入员工事实审核"],
    }


def normalize_tags(tags: Any) -> list[str]:
    if not isinstance(tags, list):
        return ["本地生活", "餐饮探店", "酒旅攻略", "小红书种草", "团购套餐", "周末去哪儿", "到店体验", "收藏备用"]
    clean = []
    for tag in tags:
        value = clean_tag(tag)
        if value and value not in clean:
            clean.append(value)
    return clean[:12] or ["本地生活", "餐饮探店", "酒旅攻略", "小红书种草", "团购套餐", "周末去哪儿", "到店体验", "收藏备用"]


def clean_tag(tag: Any) -> str:
    value = re.sub(r"\s+", "", str(tag or "").strip().lstrip("#"))
    if not value or len(value) > 12:
        return ""
    if any(word in value for word in TAG_BANNED_WORDS):
        return ""
    return value


def normalize_tag_list(tags: Any, fallback: list[str], limit: int) -> list[str]:
    source = tags if isinstance(tags, list) else []
    clean: list[str] = []
    for tag in source + fallback:
        value = clean_tag(tag)
        if value and value not in clean:
            clean.append(value)
        if len(clean) >= limit:
            break
    return clean


def normalize_tag_buckets(result: dict[str, Any], payload: DraftRequest) -> dict[str, list[str]]:
    profile = payload.merchant_profile or {}
    category = str(profile.get("category") or payload.lane or "餐饮").strip()
    city = str(profile.get("city") or "").strip()
    district = str(profile.get("district") or "").strip()
    precise_base = [f"{city}{category}" if city else f"{category}探店", f"{district}美食" if district and category == "餐饮" else f"{district}{category}" if district else "本地生活"]
    traffic = normalize_tag_list(result.get("tags_traffic"), ["探店", "本地生活", "美食推荐" if category == "餐饮" else "旅行攻略"], 3)
    precise = normalize_tag_list(result.get("tags_precise"), precise_base, 3)
    longtail = normalize_tag_list(result.get("tags_longtail"), ["一人食", "周末去哪儿"] if category == "餐饮" else ["周末去哪儿", "适合带娃"], 2)
    return {"tags_traffic": traffic, "tags_precise": precise, "tags_longtail": longtail}


def normalize_photo_checklist(raw: Any, payload: DraftRequest) -> dict[str, Any]:
    profile = payload.merchant_profile or {}
    category = str(profile.get("category") or payload.lane or "餐饮")
    default_items = [
        {"order": 1, "subject": "门头招牌正面", "tip": "站远一点拍完整店招，画面保持水平"},
        {"order": 2, "subject": "招牌菜俯拍", "tip": "垂直 90° 拍，留出右下角文字位"},
        {"order": 3, "subject": "菜品细节特写", "tip": "靠近拍热气、酱汁、切面或拉丝细节"},
        {"order": 4, "subject": "餐桌全景", "tip": "3-4 个菜品摆盘后斜上 45° 拍"},
        {"order": 5, "subject": "就餐场景", "tip": "拍朋友夹菜或举杯，突出真实氛围"},
        {"order": 6, "subject": "菜单/价签", "tip": "拍清价格和套餐信息，避免反光"},
        {"order": 7, "subject": "店内环境", "tip": "选择自然光位置，避开杂乱背景"},
    ]
    if "酒旅" in category:
        default_items = [
            {"order": 1, "subject": "门头或楼体入口", "tip": "拍清招牌和入口，方便用户识别"},
            {"order": 2, "subject": "房型全景", "tip": "站在门口广角拍，床和窗都入镜"},
            {"order": 3, "subject": "床品细节", "tip": "近景拍枕头、床单、灯光氛围"},
            {"order": 4, "subject": "卫浴细节", "tip": "保持台面干净，拍清干湿分离"},
            {"order": 5, "subject": "窗景/风景", "tip": "白天自然光拍，窗框做前景"},
            {"order": 6, "subject": "早餐或公共区", "tip": "拍出可停留、可放松的场景"},
            {"order": 7, "subject": "地段标识", "tip": "拍附近地标或路牌，证明位置"},
        ]
    default_tips = ["自然光优先，关闭头顶白炽灯", "手机网格线打开，主体放在三分线上", "每个角度多拍 3 张，后期挑最好的"]
    if not isinstance(raw, dict):
        return {"items": default_items, "tips": default_tips}
    items = raw.get("items") if isinstance(raw.get("items"), list) else []
    tips = raw.get("tips") if isinstance(raw.get("tips"), list) else []
    normalized_items = []
    for index, item in enumerate(items[:9], start=1):
        if not isinstance(item, dict):
            continue
        subject = str(item.get("subject") or "").strip()
        tip = str(item.get("tip") or "").strip()
        if subject and tip:
            normalized_items.append({"order": int(item.get("order") or index), "subject": subject, "tip": tip})
    return {
        "items": normalized_items if 5 <= len(normalized_items) <= 9 else default_items,
        "tips": [str(tip).strip() for tip in tips if str(tip).strip()][:5] or default_tips,
    }


def match_publish_timing(merchant_profile: dict[str, Any] | None, selected_title: str) -> dict[str, str]:
    profile = merchant_profile or {}
    category = str(profile.get("category") or "").strip()
    title = str(selected_title or "")
    key = "default"
    if "餐饮" in category:
        if any(word in title for word in ["早餐", "午餐"]):
            key = "餐饮_午餐"
        elif any(word in title for word in ["晚餐", "dinner", "Dinner"]):
            key = "餐饮_晚餐"
        elif any(word in title for word in ["宵夜", "夜宵", "酒吧"]):
            key = "餐饮_宵夜"
    elif "酒旅" in category:
        if any(word in title for word in ["亲子", "家庭", "带娃"]):
            key = "酒旅_家庭"
        elif any(word in title for word in ["情侣", "约会"]):
            key = "酒旅_情侣"
    rule = PUBLISH_TIMING_RULES.get(key, PUBLISH_TIMING_RULES["default"])
    return {"weekday_slot": rule["weekday"], "weekend_slot": rule["weekend"], "reason": rule["reason"]}


COMMENT_TYPES = ("type_question", "type_answer", "type_engage")


def has_banned_text(text: str) -> bool:
    return any(word in text for word in TAG_BANNED_WORDS + ["扫码", "微信号", "加微信", "美团", "大众点评", "抖音团购"])


def fallback_engagement_comments(payload: DraftRequest) -> list[dict[str, str]]:
    profile = payload.merchant_profile or {}
    district = str(profile.get("district") or profile.get("city") or "附近").strip()
    items = profile.get("signature_items") if isinstance(profile.get("signature_items"), list) else []
    signature = str(items[0]).strip() if items else "招牌款"
    return [
        {"type": "type_question", "text": "周末去会不会排队呀"},
        {"type": "type_question", "text": f"{signature}适合第一次点吗"},
        {"type": "type_answer", "text": f"位置在{district}，到店前看清门头"},
        {"type": "type_answer", "text": "营业时间建议先看店内公告"},
        {"type": "type_answer", "text": "价格按实际点单和日期为准"},
        {"type": "type_engage", "text": "这种真实体验比硬广有用"},
        {"type": "type_engage", "text": "收藏了，下次路过想试试"},
    ]


def normalize_engagement_comments(raw: Any, payload: DraftRequest) -> list[dict[str, str]]:
    source = raw if isinstance(raw, list) else []
    clean: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in source + fallback_engagement_comments(payload):
        if not isinstance(item, dict):
            continue
        comment_type = str(item.get("type") or "").strip()
        text = re.sub(r"\s+", " ", str(item.get("text") or "").strip())
        if comment_type not in COMMENT_TYPES or not text or text in seen or has_banned_text(text):
            continue
        clean.append({"type": comment_type, "text": text[:40]})
        seen.add(text)
        if len(clean) >= 10:
            break
    return clean


def template_value(profile: dict[str, Any], key: str) -> str:
    value = profile.get(key)
    if isinstance(value, list):
        text = "、".join(str(item).strip() for item in value if str(item).strip())
        return text or "{" + key + "}"
    text = str(value or "").strip()
    return text or "{" + key + "}"


def render_private_messages(merchant_profile: dict[str, Any] | None) -> list[dict[str, str]]:
    profile = merchant_profile or {}
    category = str(profile.get("category") or "").strip()
    templates = PRIVATE_MESSAGE_TEMPLATES.get(category) or PRIVATE_MESSAGE_TEMPLATES["default"]
    values = {
        "business_hours": template_value(profile, "business_hours"),
        "address": template_value(profile, "address"),
        "avg_price": template_value(profile, "avg_price"),
        "district": template_value(profile, "district"),
        "signature_items": template_value(profile, "signature_items"),
    }
    messages = []
    for item in templates:
        template = str(item.get("template") or "")
        for key, value in values.items():
            template = template.replace("{" + key + "}", value)
        messages.append({"question": str(item.get("question") or ""), "message": template})
    return messages


def fixed_benchmark() -> dict[str, Any]:
    return {
        "accounts": ["本地生活真实体验号", "餐饮酒旅种草号"],
        "notes": ["后台固定参考方向，不开放给员工填写。"],
        "usage": "参考到店理由、价格锚点、真实体验、评论区承接；不照搬原文。",
    }


def clean_generated_result(result: dict[str, Any], payload: DraftRequest) -> dict[str, Any]:
    title = str(result.get("title") or payload.title).strip()
    fallback = fallback_draft(payload)
    content_long = str(result.get("content_long") or result.get("body") or "").strip()
    content_short = str(result.get("content_short") or "").strip()
    if not content_long or re.search(r'"title"\s*:|"body"\s*:|"content_long"\s*:', content_long):
        content_long = fallback["content_long"]
    if not content_short:
        content_short = fallback["content_short"]
    return {
        **result,
        "title": title,
        "body": content_long,
        "content_long": content_long,
        "content_short": content_short,
    }


def fallback_draft(payload: DraftRequest) -> dict[str, Any]:
    profile = payload.merchant_profile or {}
    store_name = str(profile.get("store_name") or "这家店").strip()
    district = str(profile.get("district") or "").strip()
    signature_items = profile.get("signature_items") if isinstance(profile.get("signature_items"), list) else []
    selling_points = profile.get("selling_points") if isinstance(profile.get("selling_points"), list) else []
    item_text = "、".join(str(item).strip() for item in signature_items[:3] if str(item).strip()) or "招牌产品"
    point_text = "、".join(str(item).strip() for item in selling_points[:3] if str(item).strip()) or "真实体验"
    place_text = f"在{district}" if district else ""
    if payload.style == "style_pro":
        body = (
            f"我会把{store_name}{place_text}放进备选清单，主要是因为信息比较适合做一次理性判断。\n\n"
            f"围绕「{payload.title}」，正文建议先交代位置、人均、营业时间，再写{item_text}的实际体验。"
            f"主观感受控制在三成左右，重点说明{point_text}，让用户知道适不适合自己。\n\n"
            "最后补一句预约、团购或到店核销注意事项。这样读起来不像广告，也能帮助真正准备到店的人做决定。"
        )
    elif payload.style == "style_contrast":
        body = (
            f"本来不想分享{store_name}{place_text}，因为这种店一火真的很难订。\n\n"
            f"但看完「{payload.title}」这个选题，我反而觉得可以讲清楚：它不是靠噱头赢，而是{point_text}比较稳。"
            f"{item_text}可以作为第一段钩子，再反问一句：为什么同类店很多，但这家更容易让人想收藏？\n\n"
            "结尾别说满，留一个悬念给评论区：适合谁、不适合谁、什么时间去体验更好。"
        )
    else:
        body = (
            f"姐妹们，{store_name}{place_text}这次真的可以认真种草一下！✨\n\n"
            f"如果你最近在看「{payload.title}」，先别急着被噱头带走，真正重要的是到店后体验能不能对上预期。"
            f"这家比较打动我的点是{point_text}，招牌可以先看{item_text}，整体会更像真实朋友安利，不像硬广。\n\n"
            "发的时候建议先写一个到店小场景，再把位置、人均、适合人群和预约/团购规则讲清楚，最后放到评论区承接具体问题～"
        )
    short = f"{store_name}{place_text}可围绕「{payload.title}」发一条种草笔记，重点写{item_text}和{point_text}，补充位置、人均、预约或团购规则，适合引导收藏、咨询和到店。"
    tag_buckets = normalize_tag_buckets({}, payload)
    return {
        "title": payload.title,
        "body": body,
        "content_long": body,
        "content_short": short,
        **tag_buckets,
        "tags": tag_buckets["tags_traffic"] + tag_buckets["tags_precise"] + tag_buckets["tags_longtail"],
        "photo_checklist": normalize_photo_checklist(None, payload),
        "publish_timing": match_publish_timing(payload.merchant_profile, payload.selected_title or payload.title),
        "engagement_comments": fallback_engagement_comments(payload),
        "private_messages": render_private_messages(payload.merchant_profile),
        "firstComment": "想看具体位置、价格或预约方式，可以评论区问。",
        "benchmark": fixed_benchmark(),
    }
