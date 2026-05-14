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
    lane: str = "餐饮"
    keyword: str = ""


class DraftRequest(BaseModel):
    title: str
    outputType: str = "标准文案"
    noteShape: str = "干货避坑"
    framework: str = "避坑警告"
    lane: str = ""
    keyword: str = ""
    material: str = ""
    photos: list[dict[str, Any]] = []


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
    try:
        return await generate_hot_titles_with_hunyuan(payload)
    except Exception:
        if os.getenv("ALLOW_LOCAL_FALLBACK", "1") == "0":
            raise
        return fallback_hot_titles(payload)


async def generate_hot_titles_with_hunyuan(payload: HotTitleRequest) -> dict[str, Any]:
    lane = payload.lane.strip() if payload.lane.strip() in {"餐饮", "酒旅"} else "餐饮"
    keyword = payload.keyword.strip() or ("新品种草 客单价对比 隐藏菜单" if lane == "餐饮" else "周末亲子房 海边民宿 节日套餐")
    prompt = """
你是本地生活小红书转化型选题策划。
目标用户是餐饮/酒旅老板，目标不是泛流量，而是让顾客收藏、咨询、团购点击、预约、核销、到店。

请基于用户输入的行业、关键词，生成 30 个“小红书本地生活转化型选题”。
必须输出严格 JSON：
{
  "items": [
    {"id":"hot_1","title":"...","platform":"小红书","heat":88,"direction":"新品种草 · 季节"}
  ]
}

选题维度要覆盖：地域、品类、季节、节日、平台流量趋势、价格锚点、隐藏菜单/隐藏玩法、差评避坑、团购核销、周末/亲子/情侣/团建场景。
标题要像真人运营写的，不要机械套模板，不要夸大承诺，不要写保证爆单。
只输出 JSON，不要解释。
""".strip()
    result = await generate_raw_json_with_hunyuan(prompt, {
        "lane": lane,
        "keyword": keyword,
        "platform": payload.platform,
    })
    items = result.get("items", [])
    if not isinstance(items, list) or not items:
        raise RuntimeError("模型没有返回有效选题")
    normalized = []
    for index, item in enumerate(items[:30]):
        normalized.append({
            "id": str(item.get("id") or f"hot_{index + 1}"),
            "title": str(item.get("title") or "").strip(),
            "platform": str(item.get("platform") or "小红书"),
            "heat": int(item.get("heat") or (88 - index % 18)),
            "direction": str(item.get("direction") or "到店理由"),
            "keyword": keyword,
        })
    return {"count": len(normalized), "items": normalized}


def fallback_hot_titles(payload: HotTitleRequest) -> dict[str, Any]:
    seeds = [
        "本周建议发新品种草，先把到店理由讲清楚",
        "客单价对比这样写，更容易让顾客觉得值",
        "隐藏菜单不要只说好吃，要说适合谁点",
        "周末到店前，顾客最关心这几个问题",
        "节日套餐别只发价格，要发使用场景",
        "团购券核销少，可能是笔记没讲清规则",
        "一张烂图这样加标注，也能变成种草图",
        "同样的菜品图，为什么别人更容易被收藏",
        "店内随手拍怎么排成九宫格更像真人推荐",
        "差评高发问题提前讲清，反而更容易成交",
    ]
    directions = ["新品种草", "客单价对比", "隐藏菜单", "节日节点", "到店理由", "差评避坑"]
    platforms = [payload.platform or "小红书", "抖音"]
    lane = payload.lane.strip() if payload.lane.strip() in {"餐饮", "酒旅"} else "餐饮"
    keyword = payload.keyword.strip() or ("新品种草 客单价对比 隐藏菜单" if lane == "餐饮" else "周末亲子房 海边民宿 节日套餐")
    items = []
    for index in range(30):
        dimension = ["地域", "品类", "季节", "节日", "平台趋势"][index % 5]
        title = f"{lane}{keyword.split()[0] if keyword.split() else ''}：{seeds[index % len(seeds)]}"
        items.append({
            "id": f"hot_{index + 1}",
            "title": title,
            "platform": platforms[index % len(platforms)],
            "heat": 72 + ((index * 7) % 27),
            "direction": f"{directions[index % len(directions)]} · {dimension}",
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
你是“特别想-Lab”的本地生活小红书带客工具，第一批目标用户是餐饮和酒旅老板。
老板真正付费的不是内容工具，而是带客结果：收藏、咨询、团购点击、预约、核销、到店。
你要根据行业、转化型选题、店铺信息、菜品/房型/价格/位置/规则，生成可审核、可手动发布的小红书图文笔记。

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
语气要像懂本地生活转化的运营顾问，清楚、克制、可执行。
文案必须是填空式可控结构，不要像全自动生成；尽量体现地点、品类、情绪、钩子、价格锚点、到店理由。
图片方案不要做 AI 生图，不要写“生成精美图片”。核心是把老板手机里的烂图变成可发布图：
1. 智能修图：曝光、色温、食物饱和度、房间通透感；
2. 小红书爆款套版：菜品/房间图加价签、特色标注、九宫格场景图；
3. 图文匹配检测：判断图片能不能证明文案里的卖点、价格、位置和规则。
如果用户上传了图片，必须基于上传图片判断：哪张适合封面、哪张适合九宫格、哪张需要重拍、哪张适合加价签/路线/预约规则。不要假设不存在的图片内容。
最后给出弱数据监控建议：阅读、收藏、私信/评论、团购点击、预估到店或核销。
""".strip()
    content: list[dict[str, Any]] = [
        {"type": "text", "text": json.dumps(user_input, ensure_ascii=False)}
    ]
    for photo in user_input.get("photos", [])[:9]:
        data_url = str(photo.get("dataUrl", ""))
        if data_url.startswith("data:image/"):
            content.append({
                "type": "image_url",
                "image_url": {"url": data_url},
            })

    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
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


async def generate_raw_json_with_hunyuan(prompt: str, user_input: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("HUNYUAN_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 HUNYUAN_API_KEY")

    base_url = os.getenv("HUNYUAN_BASE_URL", HUNYUAN_BASE_URL).rstrip("/")
    model = os.getenv("HUNYUAN_MODEL", HUNYUAN_MODEL)
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(user_input, ensure_ascii=False)},
        ],
        "temperature": 0.72,
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
    return parse_json(response.json()["choices"][0]["message"]["content"])


def parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {
        "title": "本地生活转化型笔记",
        "body": cleaned,
        "tags": ["本地生活", "餐饮探店", "酒旅攻略", "小红书种草", "团购套餐"],
        "firstComment": "想看具体套餐、位置或预约方式，可以评论区问。",
        "images": image_plan("本地生活转化型笔记"),
    }


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
        return ["本地生活", "餐饮探店", "酒旅攻略", "小红书种草", "团购套餐"]
    clean = [str(tag).strip().lstrip("#") for tag in tags if str(tag).strip()]
    return clean[:12] or ["本地生活", "餐饮探店", "酒旅攻略", "小红书种草", "团购套餐"]


def fixed_benchmark() -> dict[str, Any]:
    return {
        "accounts": ["餐饮种草号", "酒旅攻略号", "本地生活团购转化型笔记"],
        "notes": "后台固定，不开放给员工填写。",
        "usage": "参考到店理由、价格锚点、真实场景图、九宫格、评论区承接；不照搬原文和图片。",
    }


def image_plan(title: str) -> list[dict[str, str]]:
    return [
        {"page": "封面修图", "text": title, "visual": "从老板相册选 1 张最真实的菜品/房间/门头图，调亮曝光、校正色温、压 12-18 字到店钩子。", "note": "目标不是漂亮，是一眼真实、一眼知道为什么来。"},
        {"page": "价签标注", "text": "价格和卖点直接标出来", "visual": "在原图上加价签、套餐包含、适合几人、使用时间，不遮住主体。", "note": "解决用户值不值得来的判断。"},
        {"page": "九宫格场景", "text": "让顾客像提前到店", "visual": "用 6-9 张真实图：环境、招牌、细节、菜单/团购页、停车或路线、顾客视角。", "note": "小红书更吃真实场景，不吃假精致。"},
        {"page": "对比图", "text": "同价位怎么选", "visual": "套餐 A/B、平日/周末、单点/套餐做对比，加箭头和圈点标注。", "note": "把选择理由讲清楚。"},
        {"page": "图文匹配", "text": "图片要证明文案", "visual": "检查图片是否能证明菜名/房型、价格、位置、预约规则和到店理由。", "note": "不匹配就换图或改文案，避免用户不信。"},
    ]


def fallback_draft(payload: DraftRequest) -> dict[str, Any]:
    body = (
        "很多本地生活老板发小红书，第一步就走反了。\n\n"
        "不是先追热点，也不是先把图修得很高级，更不是让 AI 生成一张看起来很假的海报。\n\n"
        "真正要先看的，是这 3 件事：\n\n"
        "1. 有没有明确到店理由\n"
        "顾客看到这条笔记，要马上知道为什么今天要来、适合谁来。\n\n"
        "2. 有没有讲清价格和规则\n"
        "套餐包含什么、几个人用、什么时候能用、怎么预约，这些比空泛夸好吃更重要。\n\n"
        "3. 图片够不够真实\n"
        "店内随手拍、菜品细节、房间实拍、菜单/团购页截图，比高大上的假图更像小红书。\n\n"
        f"{payload.material}\n\n"
        "所以别急着发很多条。先把选题、真实图片和到店理由这三件事理顺。\n\n"
        "想看具体套餐/位置/预约方式，可以在评论区问。"
    )
    return {
        "title": payload.title,
        "body": body,
        "tags": ["本地生活", "餐饮探店", "酒旅攻略", "小红书种草", "团购套餐"],
        "firstComment": "想看具体套餐、位置或预约方式，可以评论区问。",
        "images": image_plan(payload.title),
    }
