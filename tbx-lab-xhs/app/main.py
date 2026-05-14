import datetime
import hashlib
import hmac
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


class ImageFactoryRequest(BaseModel):
    title: str = ""
    material: str = ""
    images: list[dict[str, Any]] = []
    photos: list[dict[str, Any]] = []


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
        "hunyuan_enable_vision": os.getenv("HUNYUAN_ENABLE_VISION", "0"),
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

    result = clean_generated_result(result, payload)
    result["title"] = result.get("title") or payload.title
    result["firstComment"] = result.get("firstComment") or result.get("first_comment") or "想要结构参考的朋友，评论扣「模板」。"
    result["tags"] = normalize_tags(result.get("tags"))
    result["benchmark"] = result.get("benchmark") or fixed_benchmark()
    result["images"] = result.get("images") or image_plan(result["title"])
    result["compliance"] = scan_text(json.dumps(result, ensure_ascii=False))
    result["status"] = "employee_review_required"
    return result


@app.post("/api/v1/xhs/image-factory")
async def image_factory(payload: ImageFactoryRequest) -> dict[str, Any]:
    if os.getenv("HUNYUAN_IMAGE_ENABLED", "0").strip() != "1":
        return {"provider": "local_layout", "items": []}

    photos = [photo for photo in payload.photos[:9] if str(photo.get("dataUrl", "")).startswith("data:image/")]
    if not photos:
        return {"provider": "hunyuan_aiart", "items": []}

    items = []
    for index, photo in enumerate(photos):
        plan = payload.images[index % len(payload.images)] if payload.images else {}
        try:
            result_image = await call_hunyuan_image_to_image(photo, plan, payload, index)
        except Exception as exc:
            items.append({"index": index, "error": str(exc)})
            continue
        items.append({"index": index, "image": result_image})
    return {"provider": "hunyuan_aiart", "items": items}


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
images: 数组，每项包含 page、text、visual、note。这里不是图片建议，而是直接可渲染到图片上的成品页内容：
- page: 页面角色，如 封面、环境页、房型页、价格页、位置页、预约页、避坑页
- text: 直接压在图片上的大标题，12 到 22 字，像小红书真实封面文案
- visual: 本页使用的排版模板和图片角色，写给系统渲染用，不要写给老板看的建议
- note: 直接压在图片上的副标题或卖点短句，18 到 34 字

安全要求：
不声称是字节、抖音、小红书官方或官方服务商。
不承诺 GMV、ROI、爆单、第一、唯一、全网最低。
不诱导扫码、加微信或站外私聊。
不编造具体店名、地址、价格、成交数据。
语气要像懂本地生活转化的运营顾问，清楚、克制、可执行。
文案必须像真实用户发的小红书笔记，不要像广告、招商页或机构营销话术。
每次生成都要换一种内容结构，不要固定三段式。可选结构包括：
1. 真实体验日记：先讲自己为什么去，再讲实际感受和适合人群。
2. 收藏清单：适合谁、怎么订、到店注意、哪个时间段更舒服。
3. 避坑提醒：哪些情况要提前问清楚，哪些人不一定适合。
4. 对比选择：同价位怎么选、周末和平日怎么选、情侣/亲子/团建怎么选。
5. 路线攻略：怎么到、附近怎么玩、几点去更合适。
不要使用“爆款”“引流”“转化”“私域”“成交”这类后台词。
尽量体现地点、品类、情绪、钩子、价格锚点、到店理由。
图片工厂不是建议文档，而是直接生成一套可发布的小红书图文笔记成品页内容。
核心是把老板手机实拍图变成“真实 + 种草感”的图文：清晰实拍图、强钩子标题、价格/位置/到店理由标签、九宫格节奏、评论区承接。
不要输出“建议加”“可以写”“适合放”这类建议式句子。要输出能直接放在图片上的标题和短句。
如果只有图片元数据，请根据标题、行业、填空信息、图片数量/横竖图/亮度来分配页面角色；不要声称看清了具体画面细节。
成品页节奏每次都要有变化。可以参考小红书常见笔记结构：封面疑问句、真实体验页、细节特写页、价格/预约页、避坑页、路线页、收藏清单页。不要所有图片都用同一种口吻。
最后给出弱数据监控建议：阅读、收藏、私信/评论、团购点击、预估到店或核销。
""".strip()
    system_prompt += "\n再次强调：images 必须是可直接渲染成图片的成品文案，不是执行建议。"
    enable_vision = os.getenv("HUNYUAN_ENABLE_VISION", "0").strip() == "1"
    clean_input = {**user_input, "photos": photo_metadata(user_input.get("photos", []))}
    user_content: str | list[dict[str, Any]]
    user_content = json.dumps(clean_input, ensure_ascii=False)
    if enable_vision:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_content}]
        for photo in user_input.get("photos", [])[:9]:
            data_url = str(photo.get("dataUrl", ""))
            if data_url.startswith("data:image/"):
                content.append({
                    "type": "image_url",
                    "image_url": {"url": data_url},
                })
        user_content = content

    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
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
        if response.status_code == 400 and enable_vision:
            request_body["messages"][1]["content"] = json.dumps(clean_input, ensure_ascii=False)
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=request_body,
            )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return parse_json(content)


def photo_metadata(photos: Any) -> list[dict[str, Any]]:
    if not isinstance(photos, list):
        return []
    metadata = []
    for index, photo in enumerate(photos[:9]):
        if not isinstance(photo, dict):
            continue
        metadata.append({
            "index": index + 1,
            "name": str(photo.get("name", ""))[:80],
            "width": photo.get("width"),
            "height": photo.get("height"),
            "orientation": photo.get("orientation", ""),
            "brightness": photo.get("brightness", ""),
        })
    return metadata


async def call_hunyuan_image_to_image(
    photo: dict[str, Any],
    plan: dict[str, Any],
    payload: ImageFactoryRequest,
    index: int,
) -> str:
    data_url = str(photo.get("dataUrl", ""))
    image_base64 = re.sub(r"^data:image/[^;]+;base64,", "", data_url)
    prompt = build_image_prompt(plan, payload, index)
    body = {
        "InputImage": image_base64,
        "Prompt": prompt,
        "RspImgType": "base64",
        "Resolution": "768:1024",
    }
    response = await tencent_tc3_request("ImageToImage", body)
    image = response.get("Response", {}).get("ResultImage")
    if not image:
        raise RuntimeError(response.get("Response", {}).get("Error", {}).get("Message", "混元生图未返回图片"))
    return f"data:image/jpeg;base64,{image}"


def build_image_prompt(plan: dict[str, Any], payload: ImageFactoryRequest, index: int) -> str:
    page = str(plan.get("page") or f"第{index + 1}张")
    title = str(plan.get("text") or payload.title)[:40]
    note = str(plan.get("note") or payload.material)[:50]
    material = payload.material[:80]
    return (
        "小红书本地生活真实种草笔记配图，保留商家实拍质感，真实自然，不要高端假大片。"
        "优化曝光、色温、通透感、清晰度和构图，适合餐饮或酒旅老板发布。"
        f"页面角色：{page}。核心卖点：{title}。补充信息：{note}。店铺信息：{material}。"
        "画面要像小红书真实用户分享：内容真实、干净、有种草氛围、不过度商业海报化。"
        "不要生成中文文字，不要水印，不要Logo，不要夸张滤镜，不要假豪华感。"
    )[:900]


async def tencent_tc3_request(action: str, body: dict[str, Any]) -> dict[str, Any]:
    secret_id = os.getenv("TENCENTCLOUD_SECRET_ID", "").strip()
    secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY", "").strip()
    if not secret_id or not secret_key:
        raise RuntimeError("未配置 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY")

    service = "aiart"
    host = "aiart.tencentcloudapi.com"
    region = os.getenv("TENCENTCLOUD_REGION", "ap-guangzhou")
    version = "2022-12-29"
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    now = datetime.datetime.utcnow()
    timestamp = int(now.timestamp())
    date = now.strftime("%Y-%m-%d")

    http_request_method = "POST"
    canonical_uri = "/"
    canonical_querystring = ""
    canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{host}\nx-tc-action:{action.lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    hashed_request_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = "\n".join([
        http_request_method,
        canonical_uri,
        canonical_querystring,
        canonical_headers,
        signed_headers,
        hashed_request_payload,
    ])

    algorithm = "TC3-HMAC-SHA256"
    credential_scope = f"{date}/{service}/tc3_request"
    hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = "\n".join([algorithm, str(timestamp), credential_scope, hashed_canonical_request])
    secret_date = hmac.new(("TC3" + secret_key).encode("utf-8"), date.encode("utf-8"), hashlib.sha256).digest()
    secret_service = hmac.new(secret_date, service.encode("utf-8"), hashlib.sha256).digest()
    secret_signing = hmac.new(secret_service, b"tc3_request", hashlib.sha256).digest()
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"{algorithm} Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
        "X-TC-Region": region,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(f"https://{host}", headers=headers, content=payload.encode("utf-8"))
    response.raise_for_status()
    return response.json()


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
    decoder = json.JSONDecoder()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, str):
            return parse_json(parsed)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    for match in re.finditer(r"\{", cleaned):
        try:
            parsed, _ = decoder.raw_decode(cleaned[match.start():])
            if isinstance(parsed, str):
                return parse_json(parsed)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    match = re.search(r'"title"\s*:', cleaned)
    if match:
        start = cleaned.rfind("{", 0, match.start())
        if start >= 0:
            try:
                parsed, _ = decoder.raw_decode(cleaned[start:])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
    return {
        "title": "本地生活转化型笔记",
        "body": cleaned[:1200],
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


def clean_generated_result(result: dict[str, Any], payload: DraftRequest) -> dict[str, Any]:
    body = result.get("body", "")
    if isinstance(body, (dict, list)):
        body = ""
    body = str(body).strip()
    if re.search(r'"title"\s*:|"body"\s*:|"images"\s*:', body):
        reparsed = parse_json(body)
        if reparsed is not result and reparsed.get("body") and not isinstance(reparsed.get("body"), (dict, list)):
            result = {**result, **reparsed}
            body = str(result.get("body", "")).strip()
    if not body or re.search(r'"title"\s*:|"body"\s*:|"images"\s*:', body):
        result["body"] = fallback_draft(payload)["body"]
    else:
        result["body"] = body
    return result


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
        {"page": "封面", "text": title[:28], "visual": "实拍图全屏封面 + 底部白色标题卡 + 价格/位置标签", "note": "一眼看懂卖点，先让用户想收藏"},
        {"page": "场景", "text": "到店第一眼就很有感觉", "visual": "实拍图大图展示 + 左上角真实到店标签", "note": "用真实环境建立信任感"},
        {"page": "卖点", "text": "这几个细节最值得看", "visual": "实拍图 + 三个手写感卖点贴纸", "note": "把房型/菜品/服务亮点讲清楚"},
        {"page": "价格", "text": "这个价位怎么选更值", "visual": "实拍图 + 价格锚点卡片 + 套餐包含条", "note": "让顾客判断值不值得下单"},
        {"page": "清单", "text": "来之前先看这张清单", "visual": "实拍图 + 收藏清单式信息卡", "note": "位置、预约、核销和适合人群一次说清"},
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
