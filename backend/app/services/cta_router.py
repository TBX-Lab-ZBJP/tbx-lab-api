CTA_RULES = {
    "dry_tutorial": {
        "landing": "L0_SCRIPT",
        "text": "评论扣「脚本」，免费帮你写一条威海本地推文案",
    },
    "case_study": {
        "landing": "L0_DIAGNOSIS",
        "text": "评论扣「诊断」，给你的店免费做一次抖音体检",
    },
    "daily_personal": {
        "landing": "L1_99",
        "text": "本周六威海线下小聚，¥99 一起拆解真实案例，私信「体验课」",
    },
    "quote_short": {
        "landing": "L0_FORBIDDEN",
        "text": "评论扣「违禁词」，免费帮你扫一下文案有没有雷",
    },
    "long_deep": {
        "landing": "L1_99",
        "text": "想知道完整方法？¥99 线下 2 小时讲透，私信「体验课」",
    },
}


def route_cta(note_shape: str) -> dict:
    return CTA_RULES.get(note_shape, CTA_RULES["dry_tutorial"])
