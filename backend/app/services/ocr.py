from PIL import Image
import pytesseract


def extract_text(image_path: str) -> dict:
    try:
        text = pytesseract.image_to_string(Image.open(image_path), lang="chi_sim+eng")
        engine = "tesseract"
    except Exception as exc:
        text = ""
        engine = "manual_fallback"
        return {
            "engine": engine,
            "text": text,
            "fields": {},
            "warning": f"OCR 未可用，请人工回填关键指标。原因：{exc}",
        }
    return {"engine": engine, "text": text, "fields": parse_metrics(text), "warning": ""}


def parse_metrics(text: str) -> dict:
    fields: dict[str, int] = {}
    aliases = {
        "exposure": ["曝光", "播放", "展现"],
        "likes": ["点赞"],
        "saves": ["收藏"],
        "comments": ["评论"],
        "follows": ["涨粉", "新增粉丝"],
    }
    for key, words in aliases.items():
        for word in words:
            if word in text:
                fields[key] = 0
    return fields
