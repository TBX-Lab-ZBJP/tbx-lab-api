from dataclasses import dataclass

IDENTITY_RED_LINES = [
    "字节跳动",
    "字节",
    "官方服务商",
    "官方营销服务商",
    "威海特别想文化传媒有限公司",
    "霸王茶姬",
    "喜茶",
]

PROHIBITED_WORDS = [
    "保证ROI",
    "保证 GMV",
    "保证GMV",
    "全网最低",
    "第一",
    "唯一",
    "包过",
    "稳赚",
    "加我微信",
    "微信号",
    "扫码",
    "¥2,980",
    "2980",
    "¥998",
    "998/年",
]

REPLACEMENTS = {
    "保证ROI": "尽量提升投产表现",
    "保证GMV": "帮助你看懂成交问题",
    "全网最低": "近期友好价",
    "第一": "靠前",
    "唯一": "更适合",
    "包过": "通过率更稳",
    "加我微信": "评论扣关键词",
    "微信号": "私信领取",
    "扫码": "私信领取",
}


@dataclass
class ScanResult:
    passed: bool
    risk_terms: list[dict]
    score: int
    suggestions: list[str]


def scan_text(text: str) -> ScanResult:
    risk_terms: list[dict] = []
    suggestions: list[str] = []
    for word in IDENTITY_RED_LINES:
        if word in text:
            risk_terms.append({"word": word, "severity": "block", "type": "identity_red_line"})
            suggestions.append(f"删除「{word}」，不得暴露机构身份或头部品牌案例。")
    for word in PROHIBITED_WORDS:
        if word in text:
            risk_terms.append({"word": word, "severity": "high", "type": "platform_or_claim"})
            suggestions.append(f"将「{word}」改为「{REPLACEMENTS.get(word, '更克制的表达')}」。")
    score = max(0, 100 - len([r for r in risk_terms if r["severity"] == "block"]) * 35 - len(risk_terms) * 10)
    return ScanResult(
        passed=not any(r["severity"] == "block" for r in risk_terms) and score >= 80,
        risk_terms=risk_terms,
        score=score,
        suggestions=suggestions,
    )
