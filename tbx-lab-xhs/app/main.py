import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"

HUNYUAN_BASE_URL = "https://tokenhub.tencentmaas.com/v1"
HUNYUAN_MODEL = "hunyuan-2.0-instruct-20251111"

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


class HotTitleRequest(BaseModel):
    platform: str = "小红书"
    lane: str = "餐饮"
    keyword: str = ""


class DraftRequest(BaseModel):
    title: str
    outputType: str = "标准笔记素材包"
    noteShape: str = "标准笔记素材包"
    framework: str = "避坑警告"
    lane: str = ""
    keyword: str = ""
    material: str = ""


class ScanRequest(BaseModel):
    text: str = ""


@app.get("/")
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "tbx-lab-xhs"}


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
必须输出严格 JSON：
{
  "items": [
    {"id":"hot_1","title":"...","platform":"小红书","heat":88,"direction":"新品种草 · 季节","source_style":"真实体验日记"}
  ]
}
标题要像真实运营写的，不要夸大承诺，不要写保证爆单。只输出 JSON。
""".strip()
    result = await generate_raw_json_with_hunyuan(prompt, {
        "lane": lane,
        "keyword": keyword,
        "platform": payload.platform,
        "reference_pool": reference_pool,
    })
    items = result.get("items", [])
    if not isinstance(items, list) or not items:
        raise RuntimeError("模型没有返回有效选题")
    normalized = []
    for index, item in enumerate(items[:30]):
        normalized.append({
            "id": str(item.get("id") or f"hot_{index + 1}"),
            "title": str(item.get("title") or "").strip(),
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
    items = []
    for index in range(30):
        base = pool[index % len(pool)]
        title = base["title"]
        if keyword and index % 3 == 0:
            title = f"{keyword.split()[0]}｜{title}"
        if index >= len(pool):
            title = f"{title}（{modifiers[index % len(modifiers)]}）"
        items.append({
            "id": f"hot_{index + 1}",
            "title": title,
            "platform": platforms[index % len(platforms)],
            "heat": 72 + ((index * 7) % 27),
            "direction": base["direction"],
            "source_style": base["style"],
            "keyword": keyword,
        })
    return {"count": len(items), "items": items}


@app.post("/api/v1/xhs/scan")
def scan(payload: ScanRequest) -> dict[str, Any]:
    return scan_text(payload.text)


@app.post("/api/v1/xhs/draft")
async def draft(payload: DraftRequest) -> dict[str, Any]:
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
    result["tags"] = normalize_tags(result.get("tags"))
    result["benchmark"] = result.get("benchmark") or fixed_benchmark()
    result["compliance"] = scan_text(json.dumps(result, ensure_ascii=False))
    result["status"] = "employee_review_required"
    result["outputType"] = "标准笔记素材包"
    return result


async def generate_with_hunyuan(user_input: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("HUNYUAN_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 HUNYUAN_API_KEY")

    base_url = os.getenv("HUNYUAN_BASE_URL", HUNYUAN_BASE_URL).rstrip("/")
    model = os.getenv("HUNYUAN_MODEL", HUNYUAN_MODEL)
    system_prompt = """
你是“特别想-Lab”的本地生活小红书带客素材包工具，第一批目标用户是餐饮和酒旅老板。
老板真正付费的不是内容工具，而是带客结果：收藏、咨询、团购点击、预约、核销、到店。
你要根据行业、爆款选题参考、店铺信息、菜品/房型/价格/位置/规则，生成可审核、可手动发布的小红书标准笔记素材包。
必须输出严格 JSON，不要 Markdown，不要代码块。字段：
title: 字符串
body: 字符串，包含完整正文
tags: 字符串数组，8 到 12 个标签，不带 # 号
firstComment: 字符串
benchmark: 对标参考对象，包含 accounts、notes、usage
安全要求：
1. 不声称是字节、抖音、小红书官方或官方服务商。
2. 不承诺 GMV、ROI、爆单、第一、唯一、全网最低。
3. 不诱导扫码、加微信或站外私聊。
4. 不编造具体店名、地址、价格、成交数据。
文案必须像真实用户发的小红书笔记，不要像广告、招商页或机构营销话术。
正文允许自然使用 5 到 10 个 emoji，但不要每句话都堆。
不要使用“实时榜单”“真实实时数据”口径，统一使用“爆款选题参考”“行业爆款标题”口径。
""".strip()
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
    clean = [str(tag).strip().lstrip("#") for tag in tags if str(tag).strip()]
    return clean[:12] or ["本地生活", "餐饮探店", "酒旅攻略", "小红书种草", "团购套餐", "周末去哪儿", "到店体验", "收藏备用"]


def fixed_benchmark() -> dict[str, Any]:
    return {
        "accounts": ["本地生活真实体验号", "餐饮酒旅种草号"],
        "notes": ["后台固定参考方向，不开放给员工填写。"],
        "usage": "参考到店理由、价格锚点、真实体验、评论区承接；不照搬原文。",
    }


def clean_generated_result(result: dict[str, Any], payload: DraftRequest) -> dict[str, Any]:
    title = str(result.get("title") or payload.title).strip()
    body = str(result.get("body") or "").strip()
    if not body or re.search(r'"title"\s*:|"body"\s*:', body):
        body = fallback_draft(payload)["body"]
    return {
        **result,
        "title": title,
        "body": body,
    }


def fallback_draft(payload: DraftRequest) -> dict[str, Any]:
    body = (
        "先说结论：这条选题不是为了追泛流量，而是为了让真正会到店的人看懂。\n\n"
        "如果是本地生活商家，最重要的不是把话写得很满，而是把顾客会问的几件事说清楚：位置、价格、适合谁、为什么现在值得来。\n\n"
        f"围绕「{payload.title}」，建议正文先讲真实场景，再讲选择理由，最后留一个站内评论承接。\n\n"
        "发布前再核对一遍：价格是否准确、规则是否过期、有没有夸大承诺、有没有站外导流。"
    )
    return {
        "title": payload.title,
        "body": body,
        "tags": ["本地生活", "餐饮探店", "酒旅攻略", "小红书种草", "周末去哪儿", "收藏备用", "团购套餐", "真实体验"],
        "firstComment": "想看具体位置、价格或预约方式，可以评论区问。",
        "benchmark": fixed_benchmark(),
    }
