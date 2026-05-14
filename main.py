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

HUNYUAN_BASE_URL = "https://api.hunyuan.cloud.tencent.com/v1"
HUNYUAN_MODEL = "hunyuan-turbos-latest"

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

app = FastAPI(title="TBX Lab XHS Publisher", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class HotTitleRequest(BaseModel):
    platform: str = "小红书"
    lane: str = "干货避坑"
    keyword: str = "威海餐饮 抖音团购 直播没流量"


class DraftRequest(BaseModel):
    title: str
    outputType: str = "标准文案"
    noteShape: str = "干货避坑"
    framework: str = "避坑警告"
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

    result = await generate_with_hunyuan({
        "title": "模型连通性测试",
        "noteShape": "干货避坑",
        "framework": "三步拆解",
        "material": "请只返回一条很短的小红书测试文案。",
    })
    return {
        "status": "ok",
        "provider": os.getenv("LLM_PROVIDER", "hunyuan"),
        "model": os.getenv("HUNYUAN_MODEL", HUNYUAN_MODEL),
        "sample_title": result.get("title", ""),
    }


@app.post("/api/v1/xhs/hot-titles")
async def hot_titles(payload: HotTitleRequest) -> dict[str, Any]:
    seeds = [
        "为什么你的视频有播放却没人到店",
        "本地团购套餐这样设计更容易核销",
        "直播间没人停留，先改这几个动作",
        "老板别再把钱全花在投流上",
        "小店做同城内容最容易踩的坑",
        "低价套餐不等于引流款",
        "没有达人预算，也能做本地内容",
        "团购卖不动，问题可能不在流量",
        "直播开场 30 秒决定留人率",
        "门店账号冷启动先别急着发广告",
    ]
    directions = ["干货避坑", "案例拆解", "直播转化", "团购套餐", "老板日常"]
    platforms = [payload.platform or "小红书", "抖音"]
    items = []
    for index in range(30):
        title = f"{'威海老板' if index % 2 == 0 else '本地生活商家'}{[3, 5, 7, 9][index % 4]}个{seeds[index % len(seeds)]}"
        items.append({
            "id": f"hot_{index + 1}",
            "title": title,
            "platform": platforms[index % len(platforms)],
            "heat": 72 + ((index * 7) % 27),
            "direction": payload.lane or directions[index % len(directions)],
            "keyword": payload.keyword,
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

    result["title"] = result.get("title") or payload.title
    result["firstComment"] = result.get("firstComment") or result.get("first_comment") or "想先试一次的老板，评论扣「资料」。"
    result["tags"] = normalize_tags(result.get("tags"))
    result["benchmark"] = result.get("benchmark") or fixed_benchmark()
    result["images"] = result.get("images") or image_plan(result["title"])
    result["compliance"] = scan_text(json.dumps(result, ensure_ascii=False))
    result["status"] = "employee_review_required"
    return result


async def generate_with_hunyuan(user_input: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("HUNYUAN_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 HUNYUAN_API_KEY")

    base_url = os.getenv("HUNYUAN_BASE_URL", HUNYUAN_BASE_URL).rstrip("/")
    model = os.getenv("HUNYUAN_MODEL", HUNYUAN_MODEL)
    system_prompt = """
你是“特别想-Lab”的小红书内容智能发布平台，服务对象是威海本地生活商家。
你要生成员工可审核、可手动发布的小红书图文笔记。

必须输出严格 JSON，不要 Markdown，不要代码块。字段：
title: 字符串
body: 字符串，包含完整正文
tags: 字符串数组，8 到 12 个标签，不带 # 号
firstComment: 字符串
images: 数组，每项包含 page、text、visual、note

安全要求：
不声称是字节、抖音、小红书官方或官方服务商。
不承诺 GMV、ROI、爆单、第一、唯一、全网最低。
不诱导扫码、加微信或站外私聊。
不编造具体店名、地址、价格、成交数据。
语气要像懂本地商家的运营顾问，清楚、克制、可执行。
""".strip()
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_input, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.45,
        "enable_enhancement": True,
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
    return json.loads(cleaned)


def scan_text(text: str) -> dict[str, Any]:
    hits = [word for word in RED_LINES if word in text]
    return {
        "passed": len(hits) == 0,
        "risk_terms": hits,
        "score": max(0, 100 - len(hits) * 15),
        "suggestions": ["删除命中红线", "改成评论扣关键词或免费试用承接"] if hits else ["可进入员工事实审核"],
    }


def normalize_tags(tags: Any) -> list[str]:
    if not isinstance(tags, list):
        return ["威海本地生活", "威海餐饮", "实体店老板", "抖音团购", "本地生活运营"]
    clean = [str(tag).strip().lstrip("#") for tag in tags if str(tag).strip()]
    return clean[:12] or ["威海本地生活", "威海餐饮", "实体店老板", "抖音团购", "本地生活运营"]


def fixed_benchmark() -> dict[str, Any]:
    return {
        "accounts": ["教培类对标账号方向", "安先生工作室类内容结构"],
        "notes": "后台固定，不开放给员工填写。",
        "usage": "参考标题钩子、信息密度、图文分屏节奏、课程转化承接；不照搬原文和图片。",
    }


def image_plan(title: str) -> list[dict[str, str]]:
    return [
        {"page": "封面", "text": title, "visual": "蓝白版式，突出主标题，背景不放门店假图。", "note": "用于提高点击，文字控制在 18-24 字。"},
        {"page": "第 2 页", "text": "别先投流，先看套餐", "visual": "灰底黑字，左侧放错误顺序，右侧放正确顺序。", "note": "强调认知反差。"},
        {"page": "第 3 页", "text": "威海本地内容，要有本地钩子", "visual": "白底，蓝色条突出环翠区/经区/高区等地域词。", "note": "只用真实地域，不编造店名。"},
        {"page": "第 4 页", "text": "播放量不是结果，到店才是", "visual": "三段式数据框：播放、点击、核销。", "note": "为后续复盘工具做承接。"},
        {"page": "第 5 页", "text": "评论扣「资料」，先免费试一次", "visual": "蓝色 CTA 条，底部留员工审核备注位。", "note": "只承接免费试用或体验课。"},
    ]


def fallback_draft(payload: DraftRequest) -> dict[str, Any]:
    body = (
        "威海很多老板做本地生活，第一步就走反了。\n\n"
        "不是先投流，也不是先找达人，更不是看到别人爆了就照着抄一条。\n\n"
        "真正要先看的，是这 3 件事：\n\n"
        "1. 套餐有没有到店理由\n"
        "低价不等于引流款。如果套餐只是降价，老板很容易越卖越累。\n\n"
        "2. 内容有没有本地钩子\n"
        "环翠区、经区、高区的店，客群、季节、消费习惯都不一样。\n\n"
        "3. 数据有没有复盘入口\n"
        "播放量、点赞、收藏只是表面。更关键的是有没有人点团购、有没有人核销、有没有人愿意再来。\n\n"
        f"{payload.material}\n\n"
        "所以别急着把钱全花在投流上。先把套餐、内容、数据这三件事理顺。\n\n"
        "评论扣「资料」，领取一次免费工具试用。"
    )
    return {
        "title": payload.title,
        "body": body,
        "tags": ["威海本地生活", "威海餐饮", "实体店老板", "抖音团购", "本地生活运营"],
        "firstComment": "想先试一次的老板，评论扣「资料」。",
        "images": image_plan(payload.title),
    }
