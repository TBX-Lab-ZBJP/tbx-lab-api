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

app = FastAPI(title="TBX Lab XHS Publisher", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class HotTitleRequest(BaseModel):
    platform: str = "小红书"
    lane: str = ""
    keyword: str = ""


class DraftRequest(BaseModel):
    title: str
    outputType: str = "标准文案"
    noteShape: str = "干货避坑"
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
            "noteShape": "干货避坑",
            "framework": "三步拆解",
            "material": "请只返回一条很短的小红书测试文案。",
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
    seeds = [
        "为什么你的视频有播放却没人到店",
        "本地团购套餐这样设计更容易核销",
        "直播间没人停留，先改这几个动作",
        "为什么别人收藏高，你的内容却没人互动",
        "新账号冷启动先别急着追热点",
        "爆款笔记标题里常见的 3 个结构",
        "小红书内容容易没流量的几个细节",
        "封面和正文不匹配，用户会直接划走",
        "账号定位不清晰，越更越乱",
        "同样的选题，为什么别人更容易出数据",
    ]
    directions = ["干货避坑", "案例拆解", "清单教程", "经验复盘", "选题灵感"]
    platforms = [payload.platform or "小红书", "抖音"]
    lane = payload.lane.strip() or "小红书内容运营"
    keyword = payload.keyword.strip() or lane
    items = []
    for index in range(30):
        prefix = lane if index % 2 == 0 else keyword
        title = f"{prefix}{[3, 5, 7, 9][index % 4]}个{seeds[index % len(seeds)]}"
        items.append({
            "id": f"hot_{index + 1}",
            "title": title,
            "platform": platforms[index % len(platforms)],
            "heat": 72 + ((index * 7) % 27),
            "direction": directions[index % len(directions)],
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

    result["title"] = result.get("title") or payload.title
    result["firstComment"] = result.get("firstComment") or result.get("first_comment") or "想要结构参考的朋友，评论扣「模板」。"
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
你是“特别想-Lab”的小红书内容智能发布平台，服务对象是所有小红书内容运营作者。
你要根据用户填写的业务赛道、关键词、账号素材和用户痛点，生成可审核、可手动发布的小红书图文笔记。

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
语气要像懂小红书增长和内容运营的策划顾问，清楚、克制、可执行。
图文方案要参考小红书热门图文排版：真实照片/截图位、大字标题、圈点标注、步骤清单、对比箭头、重点贴纸、评论区承接。不要风格单一，不要全蓝色模板。
""".strip()
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_input, ensure_ascii=False)},
        ],
        "temperature": 0.45,
    }
    if "api.hunyuan.cloud.tencent.com" in base_url:
        request_body["enable_enhancement"] = True
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
        "suggestions": ["删除或替换命中风险词", "避免承诺效果、官方身份或站外导流", "改成平台内评论区关键词承接"] if hits else ["未发现内置风险词", "发布前仍需人工复核事实、价格、品牌身份和案例真实性"],
    }


def normalize_tags(tags: Any) -> list[str]:
    if not isinstance(tags, list):
        return ["小红书运营", "内容运营", "账号定位", "爆款笔记", "图文笔记"]
    clean = [str(tag).strip().lstrip("#") for tag in tags if str(tag).strip()]
    return clean[:12] or ["小红书运营", "内容运营", "账号定位", "爆款笔记", "图文笔记"]


def fixed_benchmark() -> dict[str, Any]:
    return {
        "accounts": ["教培类对标账号方向", "安先生工作室类内容结构"],
        "notes": "后台固定，不开放给员工填写。",
        "usage": "参考标题钩子、信息密度、图文分屏节奏、课程转化承接；不照搬原文和图片。",
    }


def image_plan(title: str) -> list[dict[str, str]]:
    return [
        {"page": "封面", "text": title, "visual": "真实照片或场景截图做底，大字标题压在上半区，右侧加 2 个圈点标注。", "note": "强钩子，控制在 18-24 字。"},
        {"page": "第 2 页", "text": "先看这 3 个信号", "visual": "三宫格清单，每格配一个小图标或截图局部。", "note": "让用户快速判断自己是否中招。"},
        {"page": "第 3 页", "text": "常见错误 vs 正确做法", "visual": "左右对比排版，中间用箭头连接，错误项用浅红，正确项用浅绿。", "note": "制造收藏价值。"},
        {"page": "第 4 页", "text": "照着改的步骤", "visual": "步骤时间线排版，配手写圈注和重点贴纸。", "note": "让内容更可执行。"},
        {"page": "第 5 页", "text": "评论区拿模板", "visual": "总结卡 + 评论区承接，不做站外导流。", "note": "只做平台内互动承接。"},
    ]


def fallback_draft(payload: DraftRequest) -> dict[str, Any]:
    body = (
        "很多账号做小红书内容，第一步就走反了。\n\n"
        "不是先追热点，也不是先套爆款模板，更不是看到别人火了就照着抄一条。\n\n"
        "真正要先看的，是这 3 件事：\n\n"
        "1. 账号定位是否清楚\n"
        "用户一眼看不懂你是谁、解决什么问题，就很难关注。\n\n"
        "2. 选题有没有具体场景\n"
        "泛泛而谈很难被收藏，越具体越容易被记住。\n\n"
        "3. 图文有没有信息层级\n"
        "封面、截图、圈点、步骤、总结要配合，而不是一屏堆满文字。\n\n"
        f"{payload.material}\n\n"
        "所以别急着日更。先把定位、选题、图文结构这三件事理顺。\n\n"
        "评论扣「模板」，领取一次内容结构参考。"
    )
    return {
        "title": payload.title,
        "body": body,
        "tags": ["小红书运营", "内容运营", "账号定位", "爆款笔记", "图文笔记"],
        "firstComment": "想要结构参考的朋友，评论扣「模板」。",
        "images": image_plan(payload.title),
    }
