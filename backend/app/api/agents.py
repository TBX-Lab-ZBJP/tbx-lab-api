import json
import tempfile
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from app.services.compliance import scan_text
from app.services.cta_router import route_cta
from app.services.llm import generate_json, stream_mock
from app.services.ocr import extract_text
from app.services.prompt_loader import knowledge_context, read_text

router = APIRouter(tags=["agents"])

HOT_TITLE_POOL: list[dict] = []
APPROVED_TITLE_POOL: list[dict] = []


@router.post("/agents/1/strategy")
async def agent1_strategy(payload: dict) -> dict:
    prompt = read_text("agents/prompts/agent1_strategy.md") + knowledge_context("extras/bp_summary.md")
    return await generate_json("agent1", prompt, payload)


@router.post("/agents/1/strategy/stream")
async def agent1_strategy_stream(payload: dict) -> StreamingResponse:
    result = await agent1_strategy(payload)
    return StreamingResponse(stream_mock(result), media_type="text/event-stream")


@router.post("/agents/2/hot-titles/collect")
def collect_hot_titles(payload: dict) -> dict:
    """Collect 30 candidate hot titles for employee first-pass review.

    v1.0 keeps this as a safe adapter boundary: manual/API/browser collection can
    be plugged in later without changing the miniapp flow.
    """
    keyword = payload.get("keyword") or "威海餐饮 抖音团购"
    platforms = payload.get("platforms") or ["xiaohongshu", "douyin"]
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
    HOT_TITLE_POOL.clear()
    for index in range(30):
        title = f"{'威海老板' if index % 2 == 0 else '本地生活商家'}{[3,5,7,9][index % 4]}个{seeds[index % len(seeds)]}"
        HOT_TITLE_POOL.append({
            "id": f"hot_{index + 1:02d}",
            "title": title,
            "platform_hint": platforms[index % len(platforms)] if platforms else "manual",
            "keyword": keyword,
            "status": "pending_employee_review",
        })
    return {"count": len(HOT_TITLE_POOL), "items": HOT_TITLE_POOL}


@router.post("/agents/2/hot-titles/approve")
def approve_hot_titles(payload: dict) -> dict:
    ids = set(payload.get("ids") or [])
    APPROVED_TITLE_POOL.clear()
    for item in HOT_TITLE_POOL:
        if item["id"] in ids:
            approved = {**item, "status": "approved_for_copywriting"}
            APPROVED_TITLE_POOL.append(approved)
    return {"count": len(APPROVED_TITLE_POOL), "items": APPROVED_TITLE_POOL}


@router.get("/agents/2/hot-titles/approved")
def approved_hot_titles() -> dict:
    return {"count": len(APPROVED_TITLE_POOL), "items": APPROVED_TITLE_POOL}


@router.post("/agents/3/draft")
async def agent3_draft(payload: dict) -> dict:
    cta = route_cta(payload.get("note_shape", "dry_tutorial"))
    prompt = read_text("agents/prompts/agent3_copywriter.md") + knowledge_context(
        "c5_compliance.md", "extras/content_ops.md"
    )
    draft = await generate_json("agent3", prompt, {**payload, "cta": cta["text"]})
    scan = scan_text(json.dumps(draft, ensure_ascii=False))
    score = await generate_json("score", read_text("agents/prompts/agent3_score.md"), draft)
    return {
        "draft": draft,
        "cta_route": cta,
        "compliance": scan.__dict__,
        "score": score,
        "next_state": "blocked_for_rewrite" if not scan.passed else "employee_review_required",
    }


@router.post("/agents/3/draft/stream")
async def agent3_draft_stream(payload: dict) -> StreamingResponse:
    result = await agent3_draft(payload)
    return StreamingResponse(stream_mock(result), media_type="text/event-stream")


@router.post("/agents/3/scan")
def scan_copy(payload: dict) -> dict:
    return scan_text(payload.get("text", "")).__dict__


@router.post("/agents/4/image/gpt")
async def gpt_image_channel(payload: dict) -> dict:
    prompt = read_text("agents/prompts/agent4_gpt_image.md")
    return {
        "channel": "gpt_image_1",
        "status": "queued_or_mocked",
        "prompt": prompt.format(**payload) if "{" in prompt else prompt,
        "review_required": True,
        "note": "v1.0 封装出图通道；无 OPENAI_API_KEY 时仅返回可复制提示词。",
    }


@router.post("/agents/4/image/gamma")
async def gamma_channel(payload: dict) -> dict:
    prompt = read_text("agents/prompts/agent4_gamma.md")
    return {
        "channel": "gamma",
        "status": "queued_or_mocked",
        "deck_prompt": prompt.format(**payload) if "{" in prompt else prompt,
        "review_required": True,
        "note": "即梦通道按 PRD 延后到 v1.5。",
    }


@router.post("/agents/5/ocr")
async def agent5_ocr(
    creator_center: UploadFile | None = File(default=None),
    douyin_laike: UploadFile | None = File(default=None),
    manual_metrics: str = Form(default="{}"),
) -> dict:
    results = []
    for file in [creator_center, douyin_laike]:
        if file is None:
            continue
        suffix = file.filename.rsplit(".", 1)[-1] if file.filename else "png"
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{suffix}") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        results.append({"filename": file.filename, **extract_text(tmp_path)})
    return {
        "ocr_results": results,
        "manual_metrics": json.loads(manual_metrics or "{}"),
        "simple_score": "needs_review",
        "next_state": "employee_review_required",
    }
