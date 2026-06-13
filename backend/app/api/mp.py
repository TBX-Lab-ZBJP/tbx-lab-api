from __future__ import annotations

import json
import os
import asyncio
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from app.services.llm import generate_text_result
from app.services.prompt_loader import knowledge_context, read_text

router = APIRouter(tags=["wechat-mp"])

TOOLS = [
    {"id": "redline", "name": "违禁词检测专家", "desc": "实时更新官方违禁词、限流词、极限词等，避免标题、内容触及红线导致作品没有流量。"},
    {"id": "shop", "name": "门店诊断专家", "desc": "帮你快速定位门店问题，先做内容、套餐还是直播，少走弯路快速成长。"},
    {"id": "script", "name": "脚本编导专家", "desc": "实时捕捉当下热门作品、话题，帮你编导出可直接拍摄的短视频或图文脚本，小白照做就能出片。"},
    {"id": "live", "name": "直播话术编写专家", "desc": "参考千万 GMV 直播场次复盘思路、1000+ 头部直播话术模板结构和素人起号案例，生成开场、留人、讲品和转化话术。"},
    {"id": "package", "name": "货盘搭建专家", "desc": "操盘运营帮你搭配门店产品，分清引流品、主推品、利润品，做好套餐组建。"},
]
TOOL_IDS = {tool["id"] for tool in TOOLS}
MAX_LOCKED_TOOL_TRIALS = 3
DAILY_PERMISSION_LIMIT = 3
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
REVIEW_TYPES = {"video": "短视频复盘", "live": "直播复盘"}

# ============================================================
# 会员套餐配置
# ------------------------------------------------------------
# 以后新增 / 调整套餐，只改这一个列表即可：
#   - 员工后台的「开通按钮」「客户筛选」「套餐统计」会自动跟着变；
#   - 小程序升级页只展示 show_in_miniapp=True 的套餐，并按价格从高到低排列。
# 字段说明：
#   id              套餐唯一标识。一旦上线产生数据就不要再改
#                   （trial_7 / full_365 已有历史数据，必须保留）。
#   days            该套餐授予的权限有效天数。
#   label           后台 / 详情页显示的权限名称。
#   admin_button    员工后台「开通」按钮上的文案，也用作客户筛选项文案。
#   summary_label   数据统计页里这一档套餐的人数标签。
#   price           价格，仅用于排序与展示，0 表示赠送。
#   upgrade_label   小程序升级页展示的套餐文案。
#   show_in_miniapp 是否在小程序升级页对客户展示。
#
# 举例：以后要加「1 个月」套餐，在列表里追加一项即可，无需改其它代码：
#   {"id": "month_30", "days": 30, "label": "30 天权限",
#    "admin_button": "开通 30 天", "summary_label": "30 天权限",
#    "price": 299, "upgrade_label": "¥299 全功能使用权（30天）",
#    "show_in_miniapp": True}
# ============================================================
PLANS: list[dict[str, Any]] = [
    {
        "id": "trial_7",
        "days": 7,
        "label": "7 天体验权限",
        "admin_button": "开通 7 天",
        "summary_label": "7 天权限",
        "price": 99,
        "upgrade_label": "¥99 线下干货体验课+全功能使用权（7天）",
        "show_in_miniapp": True,
    },
    {
        "id": "full_365",
        "days": 365,
        "label": "365 天全功能权限",
        "admin_button": "开通 365 天",
        "summary_label": "365 天权限",
        "price": 999,
        "upgrade_label": "¥999 全功能使用权（365天）",
        "show_in_miniapp": True,
    },
]
PLAN_BY_ID: dict[str, dict[str, Any]] = {plan["id"]: plan for plan in PLANS}
DEFAULT_PLAN_ID = "full_365"

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "mp_mvp.sqlite3"
DB_PATH = Path(os.getenv("MP_DB_PATH", str(DEFAULT_DB)))
WECHAT_APPID = os.getenv("WECHAT_APPID") or os.getenv("WECHAT_APP_ID", "")
WECHAT_APPSECRET = os.getenv("WECHAT_APPSECRET") or os.getenv("WECHAT_APP_SECRET", "")
DEMO_OPEN_TRIALS = os.getenv("MP_DEMO_OPEN_TRIALS", "0") == "1"
ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN", "")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(DB_PATH)
    database.row_factory = sqlite3.Row
    return database


def ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    with conn() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS mp_users (
              unionid TEXT PRIMARY KEY,
              openid TEXT NOT NULL,
              locked_tool TEXT,
              tool_trial_count INTEGER NOT NULL DEFAULT 0,
              review_video_used INTEGER NOT NULL DEFAULT 0,
              review_live_used INTEGER NOT NULL DEFAULT 0,
              permission_plan TEXT NOT NULL DEFAULT 'free',
              permission_status TEXT NOT NULL DEFAULT 'inactive',
              permission_expires_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mp_leads (
              id TEXT PRIMARY KEY,
              unionid TEXT NOT NULL,
              product TEXT NOT NULL,
              name TEXT NOT NULL,
              phone TEXT NOT NULL,
              wechat TEXT,
              staff_wechat TEXT,
              shop TEXT NOT NULL,
              contact_time TEXT NOT NULL,
              status TEXT NOT NULL,
              contacted_at TEXT,
              opened_at TEXT,
              intent_level TEXT,
              followup_note TEXT,
              next_followup_date TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS mp_activity (
              id TEXT PRIMARY KEY,
              unionid TEXT NOT NULL,
              type TEXT NOT NULL,
              title TEXT NOT NULL,
              summary TEXT NOT NULL,
              payload TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mp_daily_usage (
              unionid TEXT NOT NULL,
              feature TEXT NOT NULL,
              usage_date TEXT NOT NULL,
              count INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (unionid, feature, usage_date)
            );
            """
        )
        ensure_column(db, "mp_leads", "contacted_at", "TEXT")
        ensure_column(db, "mp_leads", "wechat", "TEXT")
        ensure_column(db, "mp_leads", "staff_wechat", "TEXT")
        ensure_column(db, "mp_leads", "opened_at", "TEXT")
        ensure_column(db, "mp_leads", "intent_level", "TEXT")
        ensure_column(db, "mp_leads", "followup_note", "TEXT")
        ensure_column(db, "mp_leads", "next_followup_date", "TEXT")


def require_admin_token(x_admin_token: str = Header(default="")) -> None:
    if ADMIN_API_TOKEN and x_admin_token != ADMIN_API_TOKEN:
        raise HTTPException(status_code=401, detail="admin_auth_required")


def today_key() -> str:
    return datetime.now(LOCAL_TZ).date().isoformat()


def feature_key(kind: str, item_id: str) -> str:
    return f"{kind}:{item_id}"


def daily_usage_counts(unionid: str, date_key: str | None = None) -> dict[str, int]:
    date_key = date_key or today_key()
    with conn() as db:
        rows = db.execute(
            "SELECT feature, count FROM mp_daily_usage WHERE unionid = ? AND usage_date = ?",
            (unionid, date_key),
        ).fetchall()
    return {row["feature"]: int(row["count"] or 0) for row in rows}


def daily_remaining(user: dict[str, Any], kind: str, item_id: str) -> int:
    if not has_active_permission(user):
        return DAILY_PERMISSION_LIMIT
    used = daily_usage_counts(user["unionid"]).get(feature_key(kind, item_id), 0)
    return max(0, DAILY_PERMISSION_LIMIT - used)


def consume_daily_permission_quota(user: dict[str, Any], kind: str, item_id: str) -> dict[str, Any] | None:
    if not has_active_permission(user):
        return None
    key = feature_key(kind, item_id)
    date_key = today_key()
    with conn() as db:
        row = db.execute(
            "SELECT count FROM mp_daily_usage WHERE unionid = ? AND feature = ? AND usage_date = ?",
            (user["unionid"], key, date_key),
        ).fetchone()
        used = int(row["count"] or 0) if row else 0
        if used >= DAILY_PERMISSION_LIMIT:
            return {
                "ok": False,
                "error": "daily_limit_used",
                "message": "今天该功能的 3 次使用次数已经用完，明天 0 点后会自动恢复。",
                "daily_limit": DAILY_PERMISSION_LIMIT,
                "daily_remaining": 0,
                "reset_at": "00:00",
                "user": public_user(user),
            }
        new_count = used + 1
        db.execute(
            """
            INSERT INTO mp_daily_usage (unionid, feature, usage_date, count, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(unionid, feature, usage_date) DO UPDATE SET
              count = excluded.count,
              updated_at = excluded.updated_at
            """,
            (user["unionid"], key, date_key, new_count, now_iso()),
        )
    return None


def lead_status(contacted_at: str | None, opened_at: str | None) -> str:
    labels = []
    if contacted_at:
        labels.append("已联系")
    if opened_at:
        labels.append("已开通")
    return " / ".join(labels) if labels else "待跟进"


def row_to_lead(row: sqlite3.Row) -> dict[str, Any]:
    lead = dict(row)
    lead["status"] = lead_status(lead.get("contacted_at"), lead.get("opened_at"))
    lead["intent_level"] = lead.get("intent_level") or "未判断"
    lead["followup_note"] = lead.get("followup_note") or ""
    lead["next_followup_date"] = lead.get("next_followup_date") or ""
    return lead


def row_to_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "unionid": row["unionid"],
        "openid": row["openid"],
        "locked_tool": row["locked_tool"],
        "tool_trial_count": row["tool_trial_count"],
        "review_used": {
            "video": bool(row["review_video_used"]),
            "live": bool(row["review_live_used"]),
        },
        "permission": {
            "plan": row["permission_plan"],
            "status": row["permission_status"],
            "expires_at": row["permission_expires_at"],
        },
        "created_at": row["created_at"],
    }


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    locked = user["locked_tool"]
    return {
        "unionid": user["unionid"],
        "openid": user["openid"],
        "locked_tool": None if DEMO_OPEN_TRIALS else locked,
        "tool_trial_count": user["tool_trial_count"],
        "tool_trials_remaining": MAX_LOCKED_TOOL_TRIALS
        if DEMO_OPEN_TRIALS
        else (
            max(0, MAX_LOCKED_TOOL_TRIALS - user["tool_trial_count"])
            if locked
            else MAX_LOCKED_TOOL_TRIALS
        ),
        "review_used": user["review_used"],
        "permission": user["permission"],
    }


def latest_lead_profiles(db: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = db.execute(
        """
        SELECT unionid, name, phone, wechat, shop, product, created_at
        FROM mp_leads
        ORDER BY created_at DESC
        """
    ).fetchall()
    profiles: dict[str, dict[str, Any]] = {}
    for row in rows:
        unionid = row["unionid"]
        if unionid not in profiles:
            profiles[unionid] = {
                "name": row["name"],
                "phone": row["phone"],
                "wechat": row["wechat"],
                "shop": row["shop"],
                "product": row["product"],
                "lead_created_at": row["created_at"],
            }
    return profiles


def save_user(user: dict[str, Any]) -> None:
    permission = user["permission"]
    with conn() as db:
        db.execute(
            """
            INSERT INTO mp_users (
              unionid, openid, locked_tool, tool_trial_count,
              review_video_used, review_live_used,
              permission_plan, permission_status, permission_expires_at,
              created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(unionid) DO UPDATE SET
              openid = excluded.openid,
              locked_tool = excluded.locked_tool,
              tool_trial_count = excluded.tool_trial_count,
              review_video_used = excluded.review_video_used,
              review_live_used = excluded.review_live_used,
              permission_plan = excluded.permission_plan,
              permission_status = excluded.permission_status,
              permission_expires_at = excluded.permission_expires_at,
              updated_at = excluded.updated_at
            """,
            (
                user["unionid"],
                user["openid"],
                user["locked_tool"],
                user["tool_trial_count"],
                int(user["review_used"]["video"]),
                int(user["review_used"]["live"]),
                permission["plan"],
                permission["status"],
                permission["expires_at"],
                user["created_at"],
                now_iso(),
            ),
        )


def get_user(unionid: str) -> dict[str, Any]:
    if not unionid:
        raise HTTPException(status_code=400, detail="missing_unionid")
    with conn() as db:
        row = db.execute("SELECT * FROM mp_users WHERE unionid = ?", (unionid,)).fetchone()
    if row:
        return row_to_user(row)
    user = {
        "unionid": unionid,
        "openid": f"openid_{unionid}",
        "locked_tool": None,
        "tool_trial_count": 0,
        "review_used": {"video": False, "live": False},
        "permission": {"plan": "free", "status": "inactive", "expires_at": None},
        "created_at": now_iso(),
    }
    save_user(user)
    return user


def exchange_wechat_code(code: str) -> dict[str, Any]:
    if not WECHAT_APPID or not WECHAT_APPSECRET:
        raise HTTPException(status_code=400, detail="missing_wechat_appid_or_secret")
    try:
        response = httpx.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={
                "appid": WECHAT_APPID,
                "secret": WECHAT_APPSECRET,
                "js_code": code,
                "grant_type": "authorization_code",
            },
            timeout=10,
            verify=False,
            trust_env=False,
        )
        data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"wechat_login_request_failed: {exc}") from exc

    if data.get("errcode"):
        raise HTTPException(status_code=400, detail={"wechat_error": data})
    if not data.get("openid"):
        raise HTTPException(status_code=400, detail={"wechat_error": data or "missing_openid_from_wechat"})
    return data


def record_activity(unionid: str, activity_type: str, title: str, summary: str, payload: dict[str, Any] | None = None) -> None:
    with conn() as db:
        db.execute(
            """
            INSERT INTO mp_activity (id, unionid, type, title, summary, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"act_{uuid4().hex[:10]}",
                unionid,
                activity_type,
                title,
                summary,
                json.dumps(payload or {}, ensure_ascii=False),
                now_iso(),
            ),
        )


@router.on_event("startup")
def startup() -> None:
    init_db()


@router.post("/login")
def login(payload: dict[str, Any]) -> dict[str, Any]:
    code = payload.get("code") or "local"
    is_dev_mock = code == "local" or payload.get("dev_mock")
    if is_dev_mock:
        unionid = payload.get("unionid") or "dev_union_local"
        openid = payload.get("openid") or "openid_local"
    else:
        session = exchange_wechat_code(code)
        openid = session["openid"]
        unionid = session.get("unionid") or openid
    user = get_user(unionid)
    user["openid"] = openid
    save_user(user)
    return {**public_user(user), "is_dev_mock": is_dev_mock}


@router.get("/users/{unionid}")
def user_status(unionid: str) -> dict[str, Any]:
    return public_user(get_user(unionid))


@router.get("/tools")
def tools() -> dict[str, Any]:
    return {"items": TOOLS, "max_trials": MAX_LOCKED_TOOL_TRIALS}


@router.post("/tools/select")
def select_tool(payload: dict[str, Any]) -> dict[str, Any]:
    user = get_user(payload.get("unionid", ""))
    tool_id = payload.get("tool_id")
    if tool_id not in TOOL_IDS:
        raise HTTPException(status_code=404, detail="unknown_tool")
    if DEMO_OPEN_TRIALS:
        return {"ok": True, "user": public_user(user), "demo_open_trials": True}
    if has_active_permission(user):
        return {"ok": True, "user": public_user(user)}
    if user["locked_tool"] and user["locked_tool"] != tool_id:
        return {"ok": False, "error": "tool_locked", "locked_tool": user["locked_tool"], "message": "您已选择一个免费试用功能，其他功能暂不可试用。"}
    user["locked_tool"] = tool_id
    save_user(user)
    return {"ok": True, "user": public_user(user)}


@router.get("/quota/{unionid}")
def quota(unionid: str) -> dict[str, Any]:
    user = get_user(unionid)
    locked = user["locked_tool"]
    active_permission = has_active_permission(user)
    usage = daily_usage_counts(user["unionid"]) if active_permission else {}
    return {
        "locked_tool": None if (DEMO_OPEN_TRIALS or active_permission) else locked,
        "tool_trial_count": user["tool_trial_count"],
        "tool_trials_remaining": MAX_LOCKED_TOOL_TRIALS
        if (DEMO_OPEN_TRIALS or active_permission)
        else (max(0, MAX_LOCKED_TOOL_TRIALS - user["tool_trial_count"]) if locked else MAX_LOCKED_TOOL_TRIALS),
        "daily_limit": DAILY_PERMISSION_LIMIT if active_permission else None,
        "daily_reset": "00:00" if active_permission else None,
        "tools": [
            {
                **tool,
                "available": True
                if (DEMO_OPEN_TRIALS or active_permission)
                else ((not locked) or locked == tool["id"]),
                "remaining": (
                    max(0, DAILY_PERMISSION_LIMIT - usage.get(feature_key("tool", tool["id"]), 0))
                    if active_permission
                    else (
                        MAX_LOCKED_TOOL_TRIALS
                        if DEMO_OPEN_TRIALS
                        else (max(0, MAX_LOCKED_TOOL_TRIALS - user["tool_trial_count"]) if locked == tool["id"] else None)
                    )
                ),
            }
            for tool in TOOLS
        ],
        "reviews": {
            "video": {
                "used": user["review_used"]["video"] if not active_permission else usage.get(feature_key("review", "video"), 0) >= DAILY_PERMISSION_LIMIT,
                "max": DAILY_PERMISSION_LIMIT if active_permission else 1,
                "remaining": max(0, DAILY_PERMISSION_LIMIT - usage.get(feature_key("review", "video"), 0)) if active_permission else (0 if user["review_used"]["video"] else 1),
            },
            "live": {
                "used": user["review_used"]["live"] if not active_permission else usage.get(feature_key("review", "live"), 0) >= DAILY_PERMISSION_LIMIT,
                "max": DAILY_PERMISSION_LIMIT if active_permission else 1,
                "remaining": max(0, DAILY_PERMISSION_LIMIT - usage.get(feature_key("review", "live"), 0)) if active_permission else (0 if user["review_used"]["live"] else 1),
            },
        },
        "permission": user["permission"],
    }


@router.post("/tools/{tool_id}/trial")
def run_trial(tool_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if tool_id not in TOOL_IDS:
        raise HTTPException(status_code=404, detail="unknown_tool")
    user = get_user(payload.get("unionid", ""))
    active_permission = has_active_permission(user)
    if active_permission:
        quota_error = consume_daily_permission_quota(user, "tool", tool_id)
        if quota_error:
            return quota_error
    if (not DEMO_OPEN_TRIALS) and (not active_permission) and user["locked_tool"] and user["locked_tool"] != tool_id:
        return {"ok": False, "error": "tool_locked", "message": "您已选择一个免费试用功能，其他功能暂不可试用。", "user": public_user(user)}
    if (not DEMO_OPEN_TRIALS) and (not active_permission) and not user["locked_tool"]:
        user["locked_tool"] = tool_id
    if (not DEMO_OPEN_TRIALS) and user["tool_trial_count"] >= MAX_LOCKED_TOOL_TRIALS and not active_permission:
        return {"ok": False, "error": "trial_used", "message": "该功能的 3 次免费试用已经用完。", "upgrade_options": upgrade_options(), "user": public_user(user)}
    if (not DEMO_OPEN_TRIALS) and not active_permission:
        user["tool_trial_count"] += 1
    save_user(user)
    tool = next(item for item in TOOLS if item["id"] == tool_id)
    user_text = payload.get("text", "")
    fallback_output = build_tool_output(tool_id, user_text)
    output = fallback_output
    ai_source = "fallback"
    ai_model = None
    ai_error = None
    if os.getenv("HUNYUAN_API_KEY", "") or os.getenv("OPENAI_API_KEY", ""):
        prompt = build_tool_prompt(tool_id)
        ai_result = asyncio.run(
            generate_text_result(
                f"mp_{tool_id}",
                prompt,
                {"tool_id": tool_id, "user_input": user_text},
                fallback=fallback_output,
            )
        )
        output = ai_result["text"]
        ai_source = ai_result.get("source", "fallback")
        ai_model = ai_result.get("model")
        ai_error = ai_result.get("error")
    record_activity(
        user["unionid"],
        "tool_trial",
        f"试用功能：{tool['name']}",
        f"第 {user['tool_trial_count']} 次试用，剩余 {max(0, MAX_LOCKED_TOOL_TRIALS - user['tool_trial_count'])} 次。",
        {"tool_id": tool_id, "input": user_text, "output": output[:500], "ai_source": ai_source, "ai_model": ai_model, "ai_error": ai_error},
    )
    return {
        "ok": True,
        "tool_id": tool_id,
        "tool_name": tool["name"],
        "output": output,
        "highlights": build_redline_highlights(output) if tool_id == "redline" else [],
        "upgrade_options": upgrade_options(),
        "daily_limit": DAILY_PERMISSION_LIMIT if active_permission else None,
        "daily_remaining": daily_remaining(user, "tool", tool_id) if active_permission else None,
        "ai_source": ai_source,
        "ai_model": ai_model,
        "ai_error": ai_error,
        "user": public_user(user),
    }


def build_redline_highlights(text: str) -> list[dict[str, Any]]:
    risk_terms = [
        "官方服务商",
        "官方营销服务商",
        "公司全称",
        "保证成交",
        "保证GMV",
        "保证ROI",
        "全网最低",
        "最低价",
        "一定爆单",
        "加我微信",
    ]
    highlights: list[dict[str, Any]] = []
    for term in risk_terms:
        start = text.find(term)
        while start >= 0:
            highlights.append({"start": start, "end": start + len(term), "reason": "风险表达"})
            start = text.find(term, start + len(term))
    return sorted(highlights, key=lambda item: item["start"])


def build_review_prompt(review_type: str) -> str:
    review_name = REVIEW_TYPES.get(review_type, "数据复盘")
    return f"""
你是特别想-Lab的本地生活智能运营顾问，正在为商家生成{review_name}。

要求：
1. 只基于用户填写的数据做经营参考，不承诺效果，不替用户自动发布内容。
2. 输出中文，结构清晰，适合小程序页面直接展示。
3. 先给一句总体判断，再给3-5条可执行建议。
4. 如果数据缺失，明确提示需要补充哪些字段，不要编造具体数据。
5. 面向抖音、小红书、直播间、团购页等本地生活场景。
6. 避免使用“保证成交、一定爆单、全网最低”等风险表达。
""".strip()


@router.post("/reviews/{review_type}")
def create_review(review_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if review_type not in REVIEW_TYPES:
        raise HTTPException(status_code=404, detail="unknown_review_type")
    user = get_user(payload.get("unionid", ""))
    active_permission = has_active_permission(user)
    if active_permission:
        quota_error = consume_daily_permission_quota(user, "review", review_type)
        if quota_error:
            return quota_error
    if user["review_used"][review_type] and not active_permission:
        return {"ok": False, "error": "review_trial_used", "message": f"{REVIEW_TYPES[review_type]}的 1 次免费试用已经用完。", "upgrade_options": upgrade_options(), "user": public_user(user)}
    if not active_permission:
        user["review_used"][review_type] = True
    save_user(user)
    fallback_output = build_live_review(payload) if review_type == "live" else build_video_review(payload)
    output = fallback_output
    ai_source = "fallback"
    ai_model = None
    ai_error = None
    if os.getenv("HUNYUAN_API_KEY", "") or os.getenv("OPENAI_API_KEY", ""):
        ai_result = asyncio.run(
            generate_text_result(
                f"mp_review_{review_type}",
                build_review_prompt(review_type),
                {"review_type": review_type, "input": payload},
                fallback=fallback_output,
            )
        )
        output = ai_result["text"]
        ai_source = ai_result.get("source", "fallback")
        ai_model = ai_result.get("model")
        ai_error = ai_result.get("error")
    record_activity(user["unionid"], "review", f"使用复盘：{REVIEW_TYPES[review_type]}", "已生成复盘建议。", {"review_type": review_type, "input": payload, "output": output[:500]})
    return {
        "ok": True,
        "review_type": review_type,
        "review_name": REVIEW_TYPES[review_type],
        "output": output,
        "daily_limit": DAILY_PERMISSION_LIMIT if active_permission else None,
        "daily_remaining": daily_remaining(user, "review", review_type) if active_permission else None,
        "ai_source": ai_source,
        "ai_model": ai_model,
        "ai_error": ai_error,
        "user": public_user(user),
    }


@router.post("/leads")
def create_lead(payload: dict[str, Any]) -> dict[str, Any]:
    user = get_user(payload.get("unionid", "dev_union_local"))
    lead = {
        "id": f"lead_{uuid4().hex[:10]}",
        "unionid": user["unionid"],
        "product": payload.get("product") or payload.get("intent") or "联系客服",
        "name": payload.get("name") or "未填写",
        "phone": payload.get("phone") or "未填写",
        "wechat": payload.get("wechat") or "未填写",
        "staff_wechat": "TBX-Lab",
        "shop": payload.get("shop") or "未填写",
        "contact_time": payload.get("contact_time") or payload.get("time") or "未填写",
        "status": "待跟进",
        "contacted_at": None,
        "opened_at": None,
        "intent_level": payload.get("intent_level") or "未判断",
        "followup_note": payload.get("followup_note") or "",
        "next_followup_date": payload.get("next_followup_date") or "",
        "created_at": now_iso(),
        "updated_at": None,
    }
    with conn() as db:
        db.execute(
            """
            INSERT INTO mp_leads (
              id, unionid, product, name, phone, wechat, staff_wechat, shop, contact_time,
              status, contacted_at, opened_at, intent_level, followup_note,
              next_followup_date, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lead["id"],
                lead["unionid"],
                lead["product"],
                lead["name"],
                lead["phone"],
                lead["wechat"],
                lead["staff_wechat"],
                lead["shop"],
                lead["contact_time"],
                lead["status"],
                lead["contacted_at"],
                lead["opened_at"],
                lead["intent_level"],
                lead["followup_note"],
                lead["next_followup_date"],
                lead["created_at"],
                lead["updated_at"],
            ),
        )
    return {"status": "received", "next_step": "员工会在员工线索台看到这条信息，然后通过企微或电话 1V1 人工跟进。", "lead": lead}


@router.get("/admin/leads", dependencies=[Depends(require_admin_token)])
def admin_leads() -> dict[str, Any]:
    with conn() as db:
        rows = db.execute("SELECT * FROM mp_leads ORDER BY created_at DESC").fetchall()
    return {"items": [row_to_lead(row) for row in rows]}


@router.patch("/admin/leads/{lead_id}", dependencies=[Depends(require_admin_token)])
def update_lead(lead_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with conn() as db:
        row = db.execute("SELECT * FROM mp_leads WHERE id = ?", (lead_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="lead_not_found")
        action = payload.get("action")
        contacted_at = row["contacted_at"]
        opened_at = row["opened_at"]
        if action == "contacted" or payload.get("status") == "已联系":
            contacted_at = contacted_at or now_iso()
        if action == "opened" or payload.get("status") == "已开通":
            opened_at = opened_at or now_iso()
        intent_level = payload.get("intent_level", row["intent_level"] or "未判断")
        followup_note = payload.get("followup_note", row["followup_note"] or "")
        next_followup_date = payload.get("next_followup_date", row["next_followup_date"] or "")
        computed_status = lead_status(contacted_at, opened_at)
        db.execute(
            """
            UPDATE mp_leads
            SET status = ?, contacted_at = ?, opened_at = ?,
                intent_level = ?, followup_note = ?, next_followup_date = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (computed_status, contacted_at, opened_at, intent_level, followup_note, next_followup_date, now_iso(), lead_id),
        )
        updated = db.execute("SELECT * FROM mp_leads WHERE id = ?", (lead_id,)).fetchone()
    if any(key in payload for key in ("intent_level", "followup_note", "next_followup_date")):
        record_activity(
            updated["unionid"],
            "followup",
            "员工更新跟进信息",
            f"意向等级：{intent_level or '未判断'}；下次回访：{next_followup_date or '未设置'}",
            {"lead_id": lead_id, "intent_level": intent_level, "followup_note": followup_note, "next_followup_date": next_followup_date},
        )
    return {"ok": True, "lead": row_to_lead(updated)}


@router.get("/admin/plans", dependencies=[Depends(require_admin_token)])
def admin_plans() -> dict[str, Any]:
    """会员套餐列表，供员工后台动态渲染开通按钮、筛选与统计。"""
    return {"items": PLANS}


@router.get("/admin/system", dependencies=[Depends(require_admin_token)])
def admin_system() -> dict[str, Any]:
    return {
        "db_path": str(DB_PATH),
        "db_parent_exists": DB_PATH.parent.exists(),
        "db_exists": DB_PATH.exists(),
        "llm_provider": "hunyuan" if os.getenv("HUNYUAN_API_KEY") else ("openai" if os.getenv("OPENAI_API_KEY") else "fallback"),
        "llm_model": os.getenv("HUNYUAN_MODEL") or os.getenv("OPENAI_MODEL") or "hunyuan-turbos-latest",
        "hunyuan_configured": bool(os.getenv("HUNYUAN_API_KEY")),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
    }


@router.get("/admin/llm-check", dependencies=[Depends(require_admin_token)])
def admin_llm_check() -> dict[str, Any]:
    result = asyncio.run(
        generate_text_result(
            "admin_llm_check",
            "你是连通性检测助手。请只回复 OK。",
            {"message": "ping"},
            fallback="FALLBACK",
        )
    )
    return {
        "ok": result.get("source") != "fallback",
        "source": result.get("source"),
        "model": result.get("model"),
        "text": result.get("text", "")[:80],
        "error": result.get("error"),
    }


BACKUP_TABLES = ("mp_users", "mp_leads", "mp_activity", "mp_daily_usage")
RESTORE_DEFAULTS: dict[str, dict[str, Any]] = {
    "mp_users": {
        "openid": "",
        "locked_tool": None,
        "tool_trial_count": 0,
        "review_video_used": 0,
        "review_live_used": 0,
        "permission_plan": "free",
        "permission_status": "inactive",
        "permission_expires_at": None,
    },
    "mp_leads": {
        "product": "联系客服",
        "name": "未填写",
        "phone": "未填写",
        "wechat": "",
        "staff_wechat": "TBX-Lab",
        "shop": "未填写",
        "contact_time": "未填写",
        "status": "待跟进",
        "contacted_at": None,
        "opened_at": None,
        "intent_level": "未判断",
        "followup_note": "",
        "next_followup_date": "",
        "updated_at": None,
    },
    "mp_activity": {"type": "restore", "title": "恢复记录", "summary": "", "payload": "{}"},
    "mp_daily_usage": {"count": 0},
}


def table_rows(db: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(f"SELECT * FROM {table}").fetchall()]


def restore_values(table: str, columns: list[str], item: dict[str, Any]) -> dict[str, Any]:
    values = {column: item.get(column) for column in columns if column in item}
    defaults = RESTORE_DEFAULTS.get(table, {})
    for column in columns:
        if column not in values and column in defaults:
            values[column] = defaults[column]
    if "created_at" in columns and not values.get("created_at"):
        values["created_at"] = now_iso()
    if "updated_at" in columns and not values.get("updated_at"):
        values["updated_at"] = now_iso()
    if table == "mp_users" and "openid" in columns and not values.get("openid"):
        values["openid"] = f"openid_{values.get('unionid') or uuid4().hex[:10]}"
    if table == "mp_daily_usage" and "updated_at" in columns and not values.get("updated_at"):
        values["updated_at"] = now_iso()
    return values


@router.get("/admin/backup", dependencies=[Depends(require_admin_token)])
def admin_backup() -> dict[str, Any]:
    init_db()
    with conn() as db:
        tables = {table: table_rows(db, table) for table in BACKUP_TABLES}
    return {
        "version": 1,
        "created_at": now_iso(),
        "db_path": str(DB_PATH),
        "tables": tables,
    }


@router.post("/admin/restore", dependencies=[Depends(require_admin_token)])
def admin_restore(payload: dict[str, Any]) -> dict[str, Any]:
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise HTTPException(status_code=400, detail="invalid_backup")
    init_db()
    restored: dict[str, int] = {}
    try:
        with conn() as db:
            for table in BACKUP_TABLES:
                rows = tables.get(table, [])
                if not isinstance(rows, list):
                    raise HTTPException(status_code=400, detail=f"invalid_table_{table}")
                columns = [row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()]
                db.execute(f"DELETE FROM {table}")
                for index, item in enumerate(rows):
                    if not isinstance(item, dict):
                        raise HTTPException(status_code=400, detail=f"invalid_row_{table}_{index}")
                    values = restore_values(table, columns, item)
                    if not values:
                        continue
                    column_names = list(values.keys())
                    placeholders = ", ".join("?" for _ in column_names)
                    try:
                        db.execute(
                            f"INSERT INTO {table} ({', '.join(column_names)}) VALUES ({placeholders})",
                            [values[column] for column in column_names],
                        )
                    except sqlite3.Error as exc:
                        raise HTTPException(status_code=400, detail=f"restore_failed_{table}_{index}: {exc}") from exc
                restored[table] = len(rows)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"restore_failed: {exc}") from exc
    return {"ok": True, "restored": restored}


@router.post("/admin/permissions", dependencies=[Depends(require_admin_token)])
def grant_permission(payload: dict[str, Any]) -> dict[str, Any]:
    user = get_user(payload.get("unionid", ""))
    plan = payload.get("plan", DEFAULT_PLAN_ID)
    plan_cfg = PLAN_BY_ID.get(plan)
    if not plan_cfg:
        raise HTTPException(status_code=404, detail="unknown_plan")
    days = int(plan_cfg["days"])
    user["permission"] = {"plan": plan, "status": "active", "expires_at": (datetime.now() + timedelta(days=days)).date().isoformat()}
    save_user(user)
    with conn() as db:
        db.execute(
            """
            UPDATE mp_leads
            SET opened_at = COALESCE(opened_at, ?),
                status = CASE
                  WHEN contacted_at IS NOT NULL THEN '已联系 / 已开通'
                  ELSE '已开通'
                END,
                updated_at = ?
            WHERE unionid = ?
            """,
            (now_iso(), now_iso(), user["unionid"]),
        )
    record_activity(
        user["unionid"],
        "permission",
        f"员工开通权限：{plan_cfg['label']}",
        f"权限到期时间：{user['permission']['expires_at']}",
        {"plan": plan, "expires_at": user["permission"]["expires_at"]},
    )
    return {"ok": True, "user": public_user(user)}


@router.get("/admin/users", dependencies=[Depends(require_admin_token)])
def admin_users() -> dict[str, Any]:
    with conn() as db:
        rows = db.execute("SELECT * FROM mp_users ORDER BY updated_at DESC").fetchall()
        profiles = latest_lead_profiles(db)
    items: list[dict[str, Any]] = []
    for row in rows:
        user = public_user(row_to_user(row))
        user["lead_profile"] = profiles.get(user["unionid"])
        items.append(user)
    return {"items": items}


@router.post("/admin/reset-test-data", dependencies=[Depends(require_admin_token)])
def admin_reset_test_data(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    confirm = (payload or {}).get("confirm")
    if confirm != "RESET_TEST_DATA":
        raise HTTPException(status_code=400, detail="missing_reset_confirmation")
    init_db()
    deleted: dict[str, int] = {}
    with conn() as db:
        for table in ("mp_daily_usage", "mp_activity", "mp_leads", "mp_users"):
            before = db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
            db.execute(f"DELETE FROM {table}")
            deleted[table] = int(before)
    return {"ok": True, "deleted": deleted}


@router.get("/admin/stats", dependencies=[Depends(require_admin_token)])
def admin_stats() -> dict[str, Any]:
    today = datetime.now().date().isoformat()
    with conn() as db:
        lead_rows = db.execute("SELECT * FROM mp_leads ORDER BY created_at DESC").fetchall()
        user_rows = db.execute("SELECT * FROM mp_users ORDER BY updated_at DESC").fetchall()
        activity_rows = db.execute("SELECT * FROM mp_activity ORDER BY created_at DESC").fetchall()
    leads = [row_to_lead(row) for row in lead_rows]
    users = [public_user(row_to_user(row)) for row in user_rows]
    activities = [dict(row) for row in activity_rows]
    total_leads = len(leads)
    contacted = sum(1 for item in leads if item.get("contacted_at"))
    opened = sum(1 for item in leads if item.get("opened_at"))
    pending = sum(1 for item in leads if not item.get("contacted_at"))
    plan_counts = {plan["id"]: 0 for plan in PLANS}
    for user in users:
        permission = user.get("permission") or {}
        if permission.get("status") == "active" and permission.get("plan") in plan_counts:
            plan_counts[permission["plan"]] += 1
    tool_usage = {tool["id"]: 0 for tool in TOOLS}
    for user in users:
        locked_tool = user.get("locked_tool")
        if locked_tool in tool_usage:
            tool_usage[locked_tool] += int(user.get("tool_trial_count") or 0)
    return {
        "summary": {
            "today_leads": sum(1 for item in leads if str(item.get("created_at", "")).startswith(today)),
            "total_leads": total_leads,
            "contacted": contacted,
            "opened": opened,
            "pending": pending,
            "contact_rate": round((contacted / total_leads) * 100, 1) if total_leads else 0,
            "open_rate": round((opened / total_leads) * 100, 1) if total_leads else 0,
            "video_reviews": sum(1 for user in users if user.get("review_used", {}).get("video")),
            "live_reviews": sum(1 for user in users if user.get("review_used", {}).get("live")),
        },
        "tool_usage": [{"id": tool["id"], "name": tool["name"], "count": tool_usage.get(tool["id"], 0)} for tool in TOOLS],
        "plan_counts": [
            {"id": plan["id"], "label": plan["summary_label"], "count": plan_counts[plan["id"]]}
            for plan in PLANS
        ],
        "pending_leads": [item for item in leads if not item.get("contacted_at")][:10],
        "followup_leads": [
            item
            for item in leads
            if item.get("next_followup_date") and str(item.get("next_followup_date")) <= today
        ][:10],
        "high_intent_leads": [
            item
            for item in leads
            if item.get("intent_level") == "高意向" and not item.get("opened_at")
        ][:10],
        "recent_activities": activities[:10],
    }


@router.get("/admin/users/{unionid}/activity", dependencies=[Depends(require_admin_token)])
def admin_user_activity(unionid: str) -> dict[str, Any]:
    user = get_user(unionid)
    with conn() as db:
        lead_rows = db.execute("SELECT * FROM mp_leads WHERE unionid = ? ORDER BY created_at DESC", (unionid,)).fetchall()
        activity_rows = db.execute("SELECT * FROM mp_activity WHERE unionid = ? ORDER BY created_at DESC", (unionid,)).fetchall()
    activities = []
    for row in activity_rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.get("payload") or "{}")
        except json.JSONDecodeError:
            item["payload"] = {}
        activities.append(item)
    return {"user": public_user(user), "leads": [row_to_lead(row) for row in lead_rows], "activities": activities}


def has_active_permission(user: dict[str, Any]) -> bool:
    permission = user.get("permission") or {}
    if permission.get("status") != "active":
        return False
    expires_at = permission.get("expires_at")
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at).date() >= datetime.now(LOCAL_TZ).date()
    except ValueError:
        return False


def upgrade_options() -> list[dict[str, Any]]:
    # 从 PLANS 派生：只展示对客户开放的套餐，按价格从高到低（高价锚点在前）。
    visible = sorted(
        (plan for plan in PLANS if plan.get("show_in_miniapp", True)),
        key=lambda plan: plan.get("price", 0),
        reverse=True,
    )
    return [
        {"label": plan["upgrade_label"], "plan": plan["id"], "enabled_in_v1": True}
        for plan in visible
    ]


def build_tool_prompt(tool_id: str) -> str:
    mapping = {
        "redline": ("mp_prompts/2_5_forbidden_scan.md", ["c5_compliance.md"]),
        "shop": ("mp_prompts/2_3_traffic_diagnosis.md", ["c2_traffic.md", "extras/bp_summary.md"]),
        "script": ("mp_prompts/2_1_live_script.md", ["c3_live_script.md", "extras/content_ops.md"]),
        "live": ("mp_prompts/2_4_live_sop.md", ["c4_live_sop.md"]),
        "package": ("mp_prompts/2_2_groupon_package.md", ["c1_groupon.md"]),
    }
    prompt_path, knowledge_files = mapping.get(tool_id, ("", []))
    base_prompt = read_text(prompt_path)
    knowledge = knowledge_context(*knowledge_files)
    if tool_id == "live":
        return (
            base_prompt
            + knowledge
            + "\n\n"
            + "\u4f60\u73b0\u5728\u662f\u300c\u672c\u5730\u751f\u6d3b\u76f4\u64ad\u8bdd\u672f\u7f16\u5199\u4e13\u5bb6\u300d\uff0c\u7528\u6237\u5df2\u7ecf\u7ed9\u4e86\u7d20\u6750\uff0c\u4e0d\u8981\u518d\u8ffd\u95ee\u8865\u5145\u8d44\u6599\u3002"
            + "\u5373\u4f7f\u4fe1\u606f\u4e0d\u5b8c\u6574\uff0c\u4e5f\u5fc5\u987b\u57fa\u4e8e\u5df2\u6709\u4fe1\u606f\u76f4\u63a5\u751f\u6210\u53ef\u4e0a\u64ad\u7684\u76f4\u64ad\u9010\u5b57\u7a3f\u3002\n"
            + "\u7981\u6b62\u8f93\u51fa\uff1a\u76f4\u64ad\u8282\u594f\u8bf4\u660e\u3001\u8fd0\u8425\u5efa\u8bae\u3001\u8d44\u6599\u6e05\u5355\u3001\u300c\u8bf7\u8865\u5145\u300d\u3001\u300c\u6211\u9700\u8981\u300d\u3001\u300c\u53ef\u4ee5\u5148\u53c2\u8003\u300d\u3002\n\n"
            + "\u8f93\u51fa\u8981\u6c42\uff1a\n"
            + "1. \u53ea\u8f93\u51fa\u76f4\u64ad\u95f4\u53ef\u76f4\u63a5\u7167\u7740\u5ff5\u7684\u8bdd\u672f\uff0c\u53e3\u8bed\u5316\uff0c\u9002\u5408\u672c\u5730\u751f\u6d3b\u5546\u5bb6\u8001\u677f\u3002\n"
            + "2. \u5fc5\u987b\u628a\u7528\u6237\u8f93\u5165\u7684\u4e1a\u52a1\u4fe1\u606f\u5199\u8fdb\u8bdd\u672f\u91cc\uff0c\u6bd4\u5982\u5730\u70b9\u3001\u4e3b\u8425\u9879\u76ee\u3001\u4ef7\u683c\u3001\u798f\u5229\u3001\u96be\u70b9\u3001\u4e92\u52a8\u8bc4\u8bba\u3002\n"
            + "3. \u4e0d\u8981\u7f16\u9020\u771f\u5b9e\u6210\u4ea4\u6570\u636e\uff0c\u4e0d\u8981\u627f\u8bfa\u6548\u679c\uff0c\u4e0d\u8981\u4f7f\u7528\u6781\u9650\u8bcd\u3002\n"
            + "4. \u6309\u8fd9\u4e2a\u7ed3\u6784\u8f93\u51fa\uff1a\n"
            + "\u300a\u76f4\u64ad\u9010\u5b57\u7a3f\u300b\n"
            + "\u4e00\u3001\u5f00\u573a\u7559\u4eba\uff0830\u79d2\uff09\n"
            + "\u4e8c\u3001\u75db\u70b9\u5171\u9e23\u4e0e\u4fe1\u4efb\u94fa\u57ab\n"
            + "\u4e09\u3001\u4ea7\u54c1/\u5957\u9910/\u6c11\u5bbf\u8be6\u7ec6\u8bb2\u89e3\n"
            + "\u56db\u3001\u4ef7\u683c\u548c\u798f\u5229\u8bf4\u6e05\u695a\n"
            + "\u4e94\u3001\u5e38\u89c1\u987e\u8651\u548c\u5f02\u8bae\u5904\u7406\n"
            + "\u516d\u3001\u8bc4\u8bba\u533a\u4e92\u52a8\u8bdd\u672f\n"
            + "\u4e03\u3001\u4e0b\u5355/\u9884\u7ea6/\u7559\u8d44\u5f15\u5bfc\n\n"
            + "\u5982\u679c\u7528\u6237\u662f\u6c11\u5bbf\u3001\u9152\u5e97\u3001\u666f\u533a\u6216\u65c5\u6e38\u7c7b\uff0c\u8bdd\u672f\u8981\u56f4\u7ed5\u300c\u4f4d\u7f6e\u3001\u4f4f\u51e0\u665a\u3001\u9002\u5408\u8c01\u3001\u4ef7\u683c\u5bf9\u6bd4\u3001\u9884\u7ea6\u89c4\u5219\u3001\u798f\u5229\u3001\u8bc4\u8bba\u4e92\u52a8\u300d\u6765\u5199\u3002"
        )
    return (
        base_prompt
        + knowledge
        + "\n\n输出要求：用中文给本地生活商家老板看，必须具体、可执行、不要编造真实店名/地址/成交数据。"
        + "如果资料不足，请说明需要老板补充什么。"
    )


def build_tool_output(tool_id: str, text: str) -> str:
    if tool_id == "redline":
        risky_terms = [
            "字节",
            "官方服务商",
            "官方营销服务商",
            "公司全称",
            "保证成交",
            "保证GMV",
            "保证ROI",
            "全网最低",
            "最低价",
            "第一",
            "唯一",
            "一定爆单",
            "加我微信",
            "微信号",
            "扫码",
        ]
        found = [term for term in risky_terms if term in (text or "")]
        if not found:
            found = ["官方服务商", "保证成交", "全网最低", "最低价", "一定爆单"]
        return (
            "违禁词检测报告\n\n"
            f"一、风险词标红\n不能用：{'、'.join(found)}。\n\n"
            "二、为什么有风险\n"
            "以上表达容易涉及平台身份红线、极限词、效果承诺或站外导流风险，可能影响标题和内容流量。\n\n"
            "三、可替换说法\n"
            "1. 不说“官方服务商”，改成“本地生活商家内容陪跑团队”。\n"
            "2. 不说“保证成交、一定爆单”，改成“结合门店真实情况持续优化”。\n"
            "3. 不说“全网最低、最低价”，改成“当前活动价、门店福利价、限时组合价”。\n"
            "4. 不直接引导加微信或扫码，改成“可留下联系方式，由员工 1V1 跟进”。\n\n"
            "四、可发布版本参考\n"
            "我们帮助本地生活商家梳理内容、套餐和复盘路径，具体效果需要结合门店真实情况持续优化。如需进一步沟通，可以留下联系方式。"
        )
    if tool_id == "script":
        return (
            "脚本编导方案\n\n"
            "一、热门选题方向\n"
            "选题：本地老板别再只发环境了，顾客真正想看的是值不值得来。\n\n"
            "二、标题\n"
            "视频有人看但没人到店？先看你的套餐有没有到店理由\n\n"
            "三、封面字\n"
            "有人看，没人来？\n\n"
            "四、镜头脚本\n"
            "镜头 1：拍门头或老板本人，字幕打出“视频有播放但没人到店？”\n"
            "镜头 2：切套餐画面，展示 2-3 个核心菜品或服务项目。\n"
            "镜头 3：拍顾客真实消费场景，突出几个人用、什么场景适合。\n"
            "镜头 4：拍团购页或菜单，不做夸张承诺，只讲清楚使用规则。\n\n"
            "五、口播逐字稿\n"
            "如果你是本地生活老板，视频有人看但没人到店，先别急着加预算。很多时候不是没流量，而是顾客没看懂为什么现在要来。你先检查三件事：第一，套餐有没有明确适合谁；第二，价格和内容是不是一眼能看懂；第三，结尾有没有告诉顾客下一步怎么做。先把这三点讲清楚，再去投流或开直播，会更稳。\n\n"
            "六、结尾引导\n"
            "想知道自己门店卡在内容、套餐还是直播，可以先做一次免费诊断。"
        )
    if tool_id == "live":
        return (
            "直播逐字稿\n\n"
            "一、开场 0-30 秒\n"
            "大家晚上好，刚进来的朋友先别急着划走。今天这场不是单纯报价格，我先用 30 秒讲清楚：这个套餐适合谁、怎么用、到店会不会踩坑。\n"
            "如果你最近想找一顿性价比高、适合朋友小聚或者家庭吃饭的套餐，可以先停一下。等我讲完你再决定要不要点开商品看。\n\n"
            "二、留人 30-90 秒\n"
            "先说清楚，不是所有人都适合拍。如果你离门店太远、近期完全没有到店计划，先不用急着下单。\n"
            "但如果你就在附近，或者这周刚好想约朋友吃一顿，那你可以听我把使用规则讲完。我们今天重点讲三件事：套餐里有什么、几个人吃合适、到店怎么核销。\n\n"
            "三、讲品 90-180 秒\n"
            "先看这个套餐，它不是一个单品，而是一组适合到店消费的组合。你下单前先看三点：第一，包含哪些菜品；第二，适合几个人；第三，周末、节假日、包间、酒水这些规则有没有限制。\n"
            "很多人买团购踩坑，不是因为价格不划算，而是因为没看清规则。所以你现在点开商品，不要只看价格，先看套餐内容和使用说明。\n\n"
            "四、产品介绍 180-300 秒\n"
            "这个套餐的核心优势是到店决策简单。你不用到店再纠结点什么，提前看好内容，到店直接核销。\n"
            "如果你是两三个人吃，就重点看份量够不够；如果是家庭或朋友聚会，就重点看环境、停车、预约和是否需要提前打电话。\n"
            "我建议你现在先点开小黄车或团购商品，看一下离你近不近、时间合不合适。如果合适，可以先收藏，晚一点和朋友确认后再下单。\n\n"
            "五、互动承接\n"
            "评论区可以直接打两个信息：你几个人吃、准备哪天去。我会按人数帮你判断这个套餐合不合适。\n"
            "如果你担心规则看不懂，也可以在评论区问，我会先帮你看使用时间、预约要求和到店核销方式。\n\n"
            "六、临门转化\n"
            "最后提醒一下，团购不要只看便宜，重点看适不适合你的场景。适合再下单，不适合就先收藏。\n"
            "刚进来的朋友，我再重复一遍：先看套餐内容，再看使用规则，最后看距离和到店时间。觉得合适的，现在可以点开商品看详情。"
        )
    if tool_id == "package":
        return (
            "货盘搭建方案\n\n"
            "一、货盘分层\n"
            "引流品：价格门槛低、顾客决策快，负责第一次到店。\n"
            "主推品：门店最想卖、顾客体验稳定，负责主要成交。\n"
            "利润品：毛利更高、适合加购或升级，负责提升客单价。\n\n"
            "二、套餐组合建议\n"
            "1. 引流套餐：选择高认知、高复购、容易出片的产品，不要塞太多限制。\n"
            "2. 主推套餐：围绕 2-4 人真实消费场景设计，讲清楚几个人用、包含什么、适合什么时候来。\n"
            "3. 利润套餐：增加招牌菜、升级项目或多人组合，提高客单价。\n\n"
            "三、直播间讲解顺序\n"
            "先讲引流品吸引停留，再讲主推品建立购买理由，最后用利润品做升级选择。\n\n"
            "四、下一步\n"
            "补充真实菜单、成本、客单价和库存压力后，可以继续细化每个套餐的价格、名称和直播话术。"
        )
    return (
        "门店诊断报告\n\n"
        "一、当前优先级判断\n"
        "先做套餐，再做内容，最后再考虑直播。原因是如果套餐没有明确到店理由，即使内容有播放，也很难带来到店和成交。\n\n"
        "二、三项排查\n"
        "1. 内容问题：标题有没有说清老板或顾客的真实痛点，前 3 秒有没有直接给理由。\n"
        "2. 套餐问题：有没有引流品、主推品、利润品，团购页是否能让顾客一眼看懂。\n"
        "3. 直播问题：如果前两项没有准备好，直播间容易变成单纯报价格。\n\n"
        "三、7 天行动建议\n"
        "第 1 天：整理现有产品和客单价。\n"
        "第 2 天：设计 1 个引流款和 1 个主推款。\n"
        "第 3 天：把套餐卖点写成 3 条短视频选题。\n"
        "第 4-5 天：拍 2 条到店理由型内容。\n"
        "第 6 天：看播放、评论、团购点击。\n"
        "第 7 天：决定是否开直播承接。"
    )


def build_video_review(payload: dict[str, Any]) -> str:
    views = float(payload.get("views") or payload.get("exposure") or 0)
    likes = float(payload.get("likes") or 0)
    saves = float(payload.get("saves") or 0)
    comments = float(payload.get("comments") or 0)
    shares = float(payload.get("shares") or 0)
    groupon = float(payload.get("groupon_clicks") or 0)
    orders = payload.get("orders") or "未填写"
    interaction = round(((likes + saves + comments + shares) / views) * 100, 2) if views else 0
    click_rate = round((groupon / views) * 100, 2) if views else 0
    diagnosis = "互动偏弱" if interaction < 1 else "互动基础可继续放大"
    conversion = "到店承接偏弱" if click_rate < 0.5 else "已有一定到店兴趣"
    return (
        "短视频复盘报告\n\n"
        f"1. 关键指标\n"
        f"播放/曝光：{views:g}\n"
        f"互动率：{interaction}%\n"
        f"团购/门店点击率：{click_rate}%\n"
        f"成交/留资/核销：{orders}\n\n"
        f"2. 初步判断\n"
        f"{diagnosis}，{conversion}。如果播放量有了但点击少，优先检查封面标题、前 3 秒表达和团购入口引导。\n\n"
        f"3. 下一步动作\n"
        f"先把标题改成老板痛点型，例如“视频有人看但没人到店，先别急着加预算”。\n"
        f"正文前 3 秒直接说问题，不要铺垫。结尾明确提醒：想看自己门店问题，可以先做一次免费诊断。\n\n"
        f"4. 建议补充\n"
        f"补充发布时间、封面截图、评论区内容和团购商品页截图后，员工可以进一步判断是内容问题、套餐问题还是承接问题。"
    )


def build_live_review(payload: dict[str, Any]) -> str:
    views = float(payload.get("views") or 0)
    clicks = float(payload.get("product_clicks") or 0)
    orders = float(payload.get("orders") or 0)
    gmv = payload.get("gmv") or "未填写"
    click_rate = round((clicks / views) * 100, 2) if views else 0
    order_rate = round((orders / clicks) * 100, 2) if clicks else 0
    click_judge = "商品点击偏弱" if click_rate < 3 else "商品点击有基础"
    order_judge = "成交承接偏弱" if order_rate < 8 else "成交承接有基础"
    return (
        "直播复盘报告\n\n"
        f"1. 关键指标\n"
        f"累计观看：{views:g}\n"
        f"商品点击率：{click_rate}%\n"
        f"点击成交率：{order_rate}%\n"
        f"成交金额 GMV：{gmv}\n\n"
        f"2. 初步判断\n"
        f"{click_judge}，{order_judge}。如果观看不少但点击少，优先改开场留人和讲品节奏；如果点击不少但成交少，优先改套餐表达和限时理由。\n\n"
        f"3. 下一步动作\n"
        f"开场 30 秒先讲适合谁，不要一上来报菜单。每 3-5 分钟重复一次核心套餐：适合人群、到店场景、包含内容、使用规则、为什么现在下单。\n"
        f"讲品后记录商品点击变化，找到点击最高的那段话术，下一场放到更靠前的位置。\n\n"
        f"4. 建议补充\n"
        f"补充直播时长、在线峰值、成交商品、退款情况和评论区高频问题后，员工可以进一步拆解留人、讲品和转化问题。"
    )


def _num(payload: dict[str, Any], key: str) -> float:
    raw = str(payload.get(key) or "").replace("%", "").replace(",", "").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _text(payload: dict[str, Any], key: str, default: str = "未填写") -> str:
    value = str(payload.get(key) or "").strip()
    return value or default


def _rate(part: float, total: float) -> float:
    return round((part / total) * 100, 2) if total else 0.0


def build_video_review(payload: dict[str, Any]) -> str:
    title = _text(payload, "title")
    publish_time = _text(payload, "publish_time")
    views = _num(payload, "views") or _num(payload, "exposure")
    finish_rate = _text(payload, "finish_rate")
    likes = _num(payload, "likes")
    saves = _num(payload, "saves")
    comments = _num(payload, "comments")
    shares = _num(payload, "shares")
    groupon = _num(payload, "groupon_clicks")
    profile = _num(payload, "profile_clicks")
    orders = _text(payload, "orders")
    note = _text(payload, "note")
    interaction = _rate(likes + saves + comments + shares, views)
    click_rate = _rate(groupon, views)
    lead_rate = _rate(profile, views)

    content_judge = "内容吸引力偏弱，优先重做标题、封面和前 3 秒钩子。" if interaction < 1 else "内容有互动基础，可以继续优化转化入口。"
    conversion_judge = "到店/团购承接偏弱，需要把套餐利益点、门店距离和行动指令说得更明显。" if click_rate < 0.5 else "到店点击已有基础，下一步看商品页和客服承接。"

    return (
        "短视频复盘报告\n\n"
        "一、核心结论\n"
        f"{content_judge}\n{conversion_judge}\n\n"
        "二、关键数据\n"
        f"选题/标题：{title}\n"
        f"发布时间：{publish_time}\n"
        f"播放/曝光：{views:g}\n"
        f"完播率：{finish_rate}\n"
        f"互动率：{interaction}%（点赞、收藏、评论、分享合计）\n"
        f"团购/门店点击率：{click_rate}%\n"
        f"主页/私信/电话点击率：{lead_rate}%\n"
        f"成交/留资/核销：{orders}\n\n"
        "三、问题定位\n"
        "1. 如果播放低：优先检查选题是否是老板真实痛点，标题是否能让本地商家立刻代入。\n"
        "2. 如果播放有但互动低：封面和前 3 秒可能太平，建议直接抛问题，不要先铺垫背景。\n"
        "3. 如果互动有但点击低：内容没有把“为什么现在要点团购/联系门店”说清楚。\n"
        "4. 如果点击有但成交低：问题大概率在套餐页、价格锚点、核销规则或客服承接。\n\n"
        "四、下一条内容怎么改\n"
        "标题改法：用“人群 + 痛点 + 反常识”结构，例如“威海老板，视频有人看但没人到店，先别急着加预算”。\n"
        "开头改法：前 3 秒只讲一个问题，不要同时讲套餐、直播、投流。\n"
        "正文改法：按“问题原因 - 错误做法 - 正确动作 - 免费诊断入口”四段写。\n"
        "结尾改法：明确说“想看自己门店是哪一步卡住，可以先做一次免费诊断”。\n\n"
        "五、员工跟进建议\n"
        "员工需要让客户补充封面截图、评论区截图、团购页截图和发布时间，再判断是内容问题、套餐问题还是承接问题。\n\n"
        f"六、补充记录\n{note}"
    )


def build_live_review(payload: dict[str, Any]) -> str:
    duration = _text(payload, "duration")
    views = _num(payload, "views")
    peak_online = _text(payload, "peak_online")
    avg_stay = _text(payload, "avg_stay") or _text(payload, "avg_watch_seconds")
    new_fans = _text(payload, "new_fans")
    comments = _text(payload, "comments")
    likes = _text(payload, "likes")
    clicks = _num(payload, "product_clicks")
    orders = _num(payload, "orders")
    gmv = _text(payload, "gmv")
    verify_count = _text(payload, "verify_count")
    note = _text(payload, "note")
    click_rate = _rate(clicks, views)
    order_rate = _rate(orders, clicks)
    avg_order = round(_num(payload, "gmv") / orders, 2) if orders else 0

    if views <= 0:
        main_problem = "直播大屏核心数据还不完整，建议先补齐累计观看、商品点击和成交订单，再做判断。"
    elif click_rate < 3:
        main_problem = "当前优先问题在“从看直播到点商品”的转化，说明开场留人、讲品顺序或福利钩子不够清楚。"
    elif order_rate < 8:
        main_problem = "当前优先问题在“点商品到成交”的承接，说明套餐权益、价格锚点、下单理由或核销说明还不够有力。"
    else:
        main_problem = "直播间已经有成交链路信号，下一步应复盘高点击、高成交的讲品片段，并把有效话术前置。"

    return (
        "直播大屏复盘报告\n\n"
        "一、核心结论\n"
        f"{main_problem}\n\n"
        "二、直播大屏关键数据\n"
        f"直播时长：{duration}\n"
        f"累计观看人数：{views:g}\n"
        f"最高在线人数：{peak_online}\n"
        f"平均停留时长：{avg_stay}\n"
        f"新增粉丝：{new_fans}\n"
        f"评论次数：{comments}\n"
        f"点赞次数：{likes}\n"
        f"商品点击人数：{clicks:g}\n"
        f"成交订单数：{orders:g}\n"
        f"成交金额 GMV：{gmv}\n"
        f"客单价估算：{avg_order if avg_order else '待补充'}\n"
        f"核销 / 到店 / 留资：{verify_count}\n\n"
        "三、五步漏斗判断\n"
        f"1. 流量进入：看累计观看和最高在线，判断直播间是否有足够进房。\n"
        f"2. 停留承接：看平均停留，如果停留短，优先改开场和每轮留人话术。\n"
        f"3. 互动信号：看评论、点赞、新增粉丝，如果互动弱，说明主播没有持续抛问题、接评论。\n"
        f"4. 商品点击：商品点击率约 {click_rate}%。如果低于 3%，优先改讲品顺序、福利表达和商品入口提醒。\n"
        f"5. 成交承接：点击成交率约 {order_rate}%。如果低于 8%，优先改套餐权益、价格对比、限时理由和核销规则。\n\n"
        "四、下一场直播优先改法\n"
        "1. 开场 30 秒先讲“这场适合谁、今天主推什么、为什么现在值得听”，不要一上来只报价格。\n"
        "2. 每个商品按“适合场景 - 几人用 - 包含内容 - 原价对比 - 使用规则 - 现在下单理由”讲完整。\n"
        "3. 每 3-5 分钟重复一次核心套餐和下单路径，照顾新进直播间的人。\n"
        "4. 评论区集中回答高频问题：几人用、怎么预约、周末能不能用、有没有限制、到店怎么核销。\n"
        "5. 下一场单独记录每轮讲品后的商品点击变化，找到最能带点击和成交的那段话术。\n\n"
        "五、员工跟进建议\n"
        "员工需要让客户补充直播大屏截图、商品点击趋势、成交商品明细和评论区高频问题。不要只看 GMV，要先判断卡在进房、停留、点击、成交还是核销。\n\n"
        f"六、补充记录\n{note}"
    )


def build_live_review(payload: dict[str, Any]) -> str:
    duration = _text(payload, "duration")
    views = _num(payload, "views")
    peak_online = _text(payload, "peak_online")
    avg_watch = _text(payload, "avg_watch_seconds")
    exposure = _num(payload, "product_exposure")
    clicks = _num(payload, "product_clicks")
    orders = _num(payload, "orders")
    gmv = _text(payload, "gmv")
    refunds = _text(payload, "refunds")
    note = _text(payload, "note")
    exposure_click_rate = _rate(clicks, exposure)
    view_click_rate = _rate(clicks, views)
    order_rate = _rate(orders, clicks)

    traffic_judge = "进房和停留需要优先优化，开场前 30 秒要先讲适合谁和为什么值得听。" if views < 1000 else "直播间已有基础流量，重点看留人、讲品和成交承接。"
    click_judge = "商品点击偏弱，说明讲品利益点不够具体，或商品入口提醒太少。" if view_click_rate < 3 else "商品点击有基础，可以继续拆成交转化。"
    order_judge = "点击后成交偏弱，优先检查套餐价格锚点、适用人群、核销规则和限时理由。" if order_rate < 8 else "成交承接有基础，下一场可以放大高转化话术。"

    return (
        "直播复盘报告\n\n"
        "一、核心结论\n"
        f"{traffic_judge}\n{click_judge}\n{order_judge}\n\n"
        "二、关键数据\n"
        f"直播时长：{duration}\n"
        f"累计观看人数：{views:g}\n"
        f"最高在线人数：{peak_online}\n"
        f"人均观看时长：{avg_watch}\n"
        f"商品曝光人数：{exposure:g}\n"
        f"商品点击人数：{clicks:g}\n"
        f"商品曝光点击率：{exposure_click_rate}%\n"
        f"观看点击率：{view_click_rate}%\n"
        f"点击成交率：{order_rate}%\n"
        f"成交订单数：{orders:g}\n"
        f"GMV：{gmv}\n"
        f"退款/未核销：{refunds}\n\n"
        "三、问题定位\n"
        "1. 观看不少但最高在线低：直播间留人弱，开场需要更快讲清楚“今天这场适合谁”。\n"
        "2. 人均观看短：主播话术节奏可能太散，需要每 3-5 分钟重复核心套餐和下单理由。\n"
        "3. 商品曝光有但点击少：讲品没有把适用场景、几人用、怎么核销、为什么划算讲透。\n"
        "4. 点击有但成交少：客户仍有顾虑，重点补“适合谁、不适合谁、到店怎么用、有没有隐藏限制”。\n"
        "5. 退款/未核销高：需要检查套餐规则是否讲清楚，避免客户误解后下单。\n\n"
        "四、下一场直播动作\n"
        "开场：30 秒内讲清楚本场福利、适合人群和最值得留下来的理由。\n"
        "留人：每 5 分钟做一次小总结，不要一直平铺商品信息。\n"
        "讲品：固定按“场景 - 人数 - 内容 - 原价对比 - 到店规则 - 现在下单理由”讲。\n"
        "逼单：不要承诺效果，用真实规则和限时节点推动决策。\n"
        "复盘：下一场记录每次讲品后的点击变化，找出最能带点击的那段话术。\n\n"
        "五、员工跟进建议\n"
        "员工需要让客户补充直播大屏截图、商品点击趋势、成交商品明细和评论区高频问题，再判断是流量问题、留人问题、讲品问题还是成交承接问题。\n\n"
        f"六、补充记录\n{note}"
    )


# Final override: standard live dashboard review fields for the customer miniapp.
def build_live_review(payload: dict[str, Any]) -> str:
    duration = _text(payload, "duration")
    live_exposure = _num(payload, "live_exposure")
    live_viewers = _num(payload, "live_viewers") or _num(payload, "views")
    product_exposure = _num(payload, "product_exposure")
    product_clicks = _num(payload, "product_clicks")
    buyers = _num(payload, "buyers")
    orders = _num(payload, "orders")
    gmv_value = _num(payload, "gmv")
    gmv = _text(payload, "gmv")
    avg_order_value = _text(payload, "avg_order_value")
    avg_watch_time = _text(payload, "avg_watch_time")
    gmv_per_1k_views = _text(payload, "gmv_per_1k_views")
    product_click_rate_input = _text(payload, "product_click_rate")
    new_fans = _text(payload, "new_fans")
    comments = _text(payload, "comments")
    verify_count = _text(payload, "verify_count", "未填写")
    note = _text(payload, "note")

    exposure_to_view_rate = _rate(live_viewers, live_exposure)
    product_show_rate = _rate(product_exposure, live_viewers)
    product_click_rate = product_click_rate_input if product_click_rate_input != "未填写" else f"{_rate(product_clicks, product_exposure)}%"
    viewer_click_rate = _rate(product_clicks, live_viewers)
    click_order_rate = _rate(orders, product_clicks)
    buyer_order_rate = _rate(buyers, live_viewers)
    avg_order = avg_order_value if avg_order_value != "未填写" else (str(round(gmv_value / orders, 2)) if orders else "未填写")
    gmv_per_1k = gmv_per_1k_views if gmv_per_1k_views != "未填写" else (str(round(gmv_value / live_viewers * 1000, 2)) if live_viewers else "未填写")

    if live_viewers <= 0:
        main_problem = "直播看播人数未填写，暂时无法判断流量进入和转化效率。先补齐直播曝光、看播、商品点击和成交数据。"
    elif product_clicks <= 0 or viewer_click_rate < 3:
        main_problem = "当前优先问题在商品点击：看播后点商品的人偏少，说明讲品顺序、福利表达或商品入口提醒还不够明确。"
    elif orders <= 0 or click_order_rate < 8:
        main_problem = "当前优先问题在成交承接：商品有人点，但下单动力不足，需要加强套餐权益、价格对比、预约/核销规则和限时理由。"
    else:
        main_problem = "直播已经形成成交链路，下一步重点复盘高点击和高成交话术，把有效片段提前到开场和每轮讲品前。"

    return (
        "直播大屏复盘报告\n\n"
        "一、核心结论\n"
        f"{main_problem}\n\n"
        "二、关键数据\n"
        f"直播时长：{duration}\n"
        f"直播曝光人数：{live_exposure:g}\n"
        f"直播看播人数：{live_viewers:g}\n"
        f"曝光进入看播率：{exposure_to_view_rate}%\n"
        f"商品曝光人数：{product_exposure:g}\n"
        f"商品点击人数：{product_clicks:g}\n"
        f"商品曝光点击率：{product_click_rate}\n"
        f"看播点击率：{viewer_click_rate}%\n"
        f"成交人数：{buyers:g}\n"
        f"成交订单数：{orders:g}\n"
        f"点击成交率：{click_order_rate}%\n"
        f"看播成交率：{buyer_order_rate}%\n"
        f"成交GMV：{gmv}\n"
        f"订单均价：{avg_order}\n"
        f"人均观看时长：{avg_watch_time}\n"
        f"千次观看成交金额：{gmv_per_1k}\n"
        f"新增粉丝数：{new_fans}\n"
        f"评论次数：{comments}\n"
        f"核销数量：{verify_count}\n\n"
        "三、五步漏斗判断\n"
        "1. 看曝光到看播：如果曝光不少但看播少，优先改封面、标题、开场利益点和进房前3秒。\n"
        "2. 看播到商品曝光：如果看播有了但商品曝光少，说明商品挂载、弹品频率或讲品节奏不够稳定。\n"
        "3. 商品曝光到点击：如果商品曝光有但点击少，优先把适合谁、包含什么、价格福利、使用规则讲得更具体。\n"
        "4. 点击到成交：如果点击有但订单少，重点补顾虑处理：怎么预约、到店怎么核销、节假日能不能用、有没有隐藏限制。\n"
        "5. 成交到核销：如果成交和核销差距大，下一步要加强下单后提醒、预约路径和客服跟进。\n\n"
        "四、下一场优先动作\n"
        "1. 开场30秒先讲适合谁、今天主推什么、为什么现在值得留下。\n"
        "2. 每轮讲品固定按：场景 - 人群 - 权益 - 价格 - 规则 - 现在下单理由。\n"
        "3. 每3-5分钟重复一次商品入口和核心福利，照顾新进入直播间的人。\n"
        "4. 评论区集中回答高频问题，用回答评论带出商品点击提醒。\n"
        "5. 下一场单独记录每轮讲品后的商品点击变化，找出最能带点击和成交的话术。\n\n"
        f"五、补充记录\n{note}"
    )
