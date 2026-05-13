from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

TOOLS = [
    {"id": "redline", "name": "违禁词检测专家", "desc": "实时更新官方违禁词、限流词、极限词等，避免标题、内容触及红线导致作品没有流量。"},
    {"id": "shop", "name": "门店诊断专家", "desc": "帮你快速定位门店问题，先做内容、套餐还是直播，少走弯路快速成长。"},
    {"id": "script", "name": "脚本编导专家", "desc": "实时捕捉当下热门作品、话题，帮你编导出可直接拍摄的短视频或图文脚本，小白照做就能出片。"},
    {"id": "live", "name": "直播话术编写专家", "desc": "参考千万 GMV 直播场次复盘思路、1000+ 头部直播话术模板结构和素人起号案例，生成开场、留人、讲品和转化话术。"},
    {"id": "package", "name": "货盘搭建专家", "desc": "操盘运营帮你搭配门店产品，分清引流品、主推品、利润品，做好套餐组建。"},
]

BASE = "/api/v1/wechat-mp"


def tool_output(tool_id: str) -> str:
    if tool_id == "redline":
        return (
            "违禁词检测报告\n\n"
            "一、风险词标红\n不能用：官方服务商、保证成交、全网最低、最低价、一定爆单。\n\n"
            "二、为什么有风险\n这些词容易涉及平台身份红线、极限词、效果承诺或站外导流风险，可能影响标题和内容流量。\n\n"
            "三、可替换说法\n官方服务商 → 本地生活商家内容陪跑团队\n保证成交 → 结合门店真实情况持续优化\n最低价 → 当前活动价 / 门店福利价\n\n"
            "四、可发布版本\n我们帮助本地生活商家梳理内容、套餐和复盘路径，具体效果需要结合门店真实情况持续优化。"
        )
    if tool_id == "shop":
        return (
            "门店诊断报告\n\n"
            "一、当前优先级判断\n先做套餐，再做内容，最后再考虑直播。\n\n"
            "二、三项排查\n1. 内容有没有讲清到店理由。\n2. 套餐有没有引流品、主推品、利润品。\n3. 直播是否具备开场、留人、讲品和成交承接。\n\n"
            "三、7 天行动建议\n第 1 天整理产品和客单价；第 2 天设计引流款；第 3 天写 3 条选题；第 4-5 天拍内容；第 6 天看数据；第 7 天决定是否开直播。"
        )
    if tool_id == "script":
        return (
            "脚本编导方案\n\n"
            "一、热门选题方向\n本地老板别再只发环境了，顾客真正想看的是值不值得来。\n\n"
            "二、标题\n视频有人看但没人到店？先看你的套餐有没有到店理由\n\n"
            "三、封面字\n有人看，没人来？\n\n"
            "四、镜头脚本\n镜头 1：拍门头或老板本人。\n镜头 2：切套餐画面。\n镜头 3：拍真实消费场景。\n镜头 4：拍团购页或菜单。\n\n"
            "五、口播逐字稿\n如果你是本地生活老板，视频有人看但没人到店，先别急着加预算。很多时候不是没流量，而是顾客没看懂为什么现在要来。"
        )
    if tool_id == "live":
        return (
            "直播逐字稿\n\n"
            "一、开场\n大家晚上好，刚进来的朋友先别急着划走。今天这场我先讲清楚这个套餐适合谁、怎么用、到店会不会踩坑。\n\n"
            "二、留人\n不是所有人都适合拍，如果你离门店太远可以先收藏；如果你就在附近，可以听我把使用规则讲完。\n\n"
            "三、讲品\n这个套餐适合朋友小聚或家庭用餐，先看包含内容、几个人用、使用时间和核销规则。\n\n"
            "四、转化\n觉得合适的，可以点开商品先看详情；不确定的可以评论区说几个人、哪天去，我帮你判断。"
        )
    return (
        "货盘搭建方案\n\n"
        "一、货盘分层\n引流品：负责第一次到店。\n主推品：负责主要成交。\n利润品：负责提升客单价。\n\n"
        "二、套餐组合建议\n引流套餐降低决策门槛；主推套餐围绕真实消费场景；利润套餐增加招牌或升级项目。\n\n"
        "三、直播讲解顺序\n先讲引流品吸引停留，再讲主推品建立购买理由，最后用利润品做升级选择。"
    )


def review_output() -> str:
    return (
        "复盘报告\n\n"
        "一、核心结论\n优先判断卡在流量、停留、点击还是成交。不要只看 GMV。\n\n"
        "二、关键判断\n如果观看不少但点击少，优先改开场留人和讲品顺序；如果点击不少但成交少，优先改套餐权益、价格锚点和核销说明。\n\n"
        "三、下一步\n下一场记录每轮讲品后的点击变化，找到最能带点击和成交的那段话术。"
    )


class Handler(BaseHTTPRequestHandler):
    def _json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("content-length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_OPTIONS(self) -> None:
        self._json({})

    def do_GET(self) -> None:
        path = unquote(self.path.split("?")[0])
        if path == f"{BASE}/tools":
            self._json({"items": [{**t, "available": True, "remaining": 3} for t in TOOLS], "max_trials": 3})
            return
        if path.startswith(f"{BASE}/quota/"):
            self._json({
                "locked_tool": None,
                "tool_trial_count": 0,
                "tool_trials_remaining": 3,
                "tools": [{**t, "available": True, "remaining": 3} for t in TOOLS],
                "reviews": {"video": {"used": False, "max": 1}, "live": {"used": False, "max": 1}},
                "permission": {"plan": "free", "status": "inactive", "expires_at": None},
            })
            return
        if path == f"{BASE}/admin/leads":
            self._json({"items": []})
            return
        if path == f"{BASE}/admin/users":
            self._json({"items": []})
            return
        self._json({"ok": True})

    def do_POST(self) -> None:
        path = unquote(self.path.split("?")[0])
        body = self._body()
        if path == f"{BASE}/login":
            self._json({"unionid": "dev_union_test", "openid": "openid_test", "locked_tool": None, "tool_trials_remaining": 3})
            return
        if path == f"{BASE}/tools/select":
            self._json({"ok": True, "user": {"locked_tool": None, "tool_trials_remaining": 3}})
            return
        if path.startswith(f"{BASE}/tools/") and path.endswith("/trial"):
            tool_id = path.split("/")[-2]
            self._json({"ok": True, "tool_id": tool_id, "output": tool_output(tool_id), "upgrade_options": []})
            return
        if path.startswith(f"{BASE}/reviews/"):
            self._json({"ok": True, "output": review_output()})
            return
        if path == f"{BASE}/leads":
            lead = {
                "product": body.get("product", "联系客服"),
                "name": body.get("name", "未填写"),
                "phone": body.get("phone", "未填写"),
                "wechat": body.get("wechat", "未填写"),
                "staff_wechat": "TBX-Lab",
                "shop": body.get("shop", "未填写"),
                "contact_time": body.get("contact_time", "未填写"),
            }
            self._json({"status": "received", "lead": lead})
            return
        self._json({"ok": True})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
    print("TBX test backend running on http://0.0.0.0:8000")
    server.serve_forever()
