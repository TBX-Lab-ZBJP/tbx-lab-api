import asyncio
import json
import os
from collections.abc import AsyncIterator

import httpx


def clean_env_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1].strip()
    return value


def normalized_base_url() -> str:
    base_url = (clean_env_value("HUNYUAN_BASE_URL") or "https://api.hunyuan.cloud.tencent.com/v1").rstrip("/")
    if "hunyuan.cloud.tencent.com" in base_url and not base_url.endswith("/v1"):
        return f"{base_url}/v1"
    return base_url


async def stream_mock(payload: dict) -> AsyncIterator[str]:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for char in text:
        yield char
        await asyncio.sleep(0.002)


async def generate_json(task: str, prompt: str, user_input: dict) -> dict:
    api_key = clean_env_value("HUNYUAN_API_KEY") or clean_env_value("OPENAI_API_KEY")
    if api_key:
        try:
            base_url = normalized_base_url()
            model = clean_env_value("HUNYUAN_MODEL") or clean_env_value("OPENAI_MODEL") or "hunyuan-turbos-latest"
            response = await httpx.AsyncClient(timeout=60).post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps(user_input, ensure_ascii=False)},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.4,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception:
            pass

    # Local deterministic fallback. Real providers can be added here without
    # changing API contracts; all endpoints already expose streaming variants.
    if task == "agent1":
        return {
            "positioning": "迪安个人 IP，威海本地生活商家培训，强调本地真实案例与可执行方法。",
            "accounts": {
                "A": "抖音视频搬运观察账号，v1.0 不做红绿灯自动止损。",
                "B": "AI 图文主账号，起号期日更，所有内容员工审核后发布。",
            },
            "weekly_rhythm": ["周一选题", "周二文案", "周三出图", "周四审核", "周五发布与回填"],
            "red_lines": ["不暴露机构身份", "不自动发布", "不编造威海店名/地址/数据"],
        }
    if task == "agent3":
        title = user_input.get("title") or "威海老板别再盲目投本地推"
        cta = user_input.get("cta", "评论扣「脚本」，免费帮你写一条威海本地推文案")
        return {
            "title": title,
            "body": f"{title}\n\n很多威海老板不是不努力，是把钱花在了看不见问题的地方。\n\n1. 先看套餐结构，再看流量入口。\n2. 先确认真实门店数据，再决定内容钩子。\n3. 员工审核后再发布，别让 AI 编店名。\n\n在环翠区、经区、高区做本地生活，最怕的是照搬外地模板。\n\n{cta}",
            "tags": ["威海本地生活", "威海餐饮", "抖音团购", "实体店老板"],
            "first_comment": "想要模板的老板，评论扣关键词，我发你可改版。",
            "status": "needs_employee_review",
        }
    if task == "score":
        body = user_input.get("body", "")
        total = 48 + min(14, body.count("威海") * 3)
        return {
            "total": total,
            "by_dim": [
                {"name": "标题", "score": 7, "max": 8, "reasons": ["含地域与老板痛点"]},
                {"name": "开头段", "score": 8, "max": 10, "reasons": ["前 3 行能切入经营焦虑"]},
                {"name": "行动召唤", "score": 6, "max": 6, "reasons": ["结尾有评论或私信 CTA"]},
            ],
            "suggestions": ["补充员工已核实的真实店铺素材。", "标签中保留至少 2 个威海地域词。"],
        }
    return {"task": task, "prompt": prompt[:300], "input": user_input}


async def generate_text_result(task: str, prompt: str, user_input: dict, fallback: str = "") -> dict:
    api_key = clean_env_value("HUNYUAN_API_KEY") or clean_env_value("OPENAI_API_KEY")
    if api_key:
        provider = "hunyuan" if clean_env_value("HUNYUAN_API_KEY") else "openai"
        try:
            base_url = normalized_base_url()
            model = clean_env_value("HUNYUAN_MODEL") or clean_env_value("OPENAI_MODEL") or "hunyuan-turbos-latest"
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": json.dumps(user_input, ensure_ascii=False)},
                        ],
                        "temperature": 0.55,
                    },
                )
            response.raise_for_status()
            return {
                "text": response.json()["choices"][0]["message"]["content"].strip(),
                "source": provider,
                "model": model,
            }
        except Exception as exc:
            return {"text": fallback, "source": "fallback", "error": str(exc)}
    return {"text": fallback, "source": "fallback", "error": "missing_api_key"}


async def generate_text(task: str, prompt: str, user_input: dict, fallback: str = "") -> str:
    result = await generate_text_result(task, prompt, user_input, fallback)
    return result["text"]
