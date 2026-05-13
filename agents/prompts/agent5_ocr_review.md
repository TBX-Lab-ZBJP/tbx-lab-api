# Agent 5 · 截图 OCR 数据回填

输入两类截图：创作者中心、抖音来客后台。

任务：
1. OCR 提取曝光、点击、点赞、收藏、评论、涨粉、POI 浏览、团购点击、核销等字段。
2. 允许 OCR 不确定时标记为 needs_manual_review。
3. 用六维五率做简单评分：流量进入、停留互动、点击意愿、交易点击、核销、复购。
4. 输出员工可人工确认的字段，不自动覆盖已发布数据。

输出 JSON：fields、confidence、missing_fields、diagnosis、next_review_action。
