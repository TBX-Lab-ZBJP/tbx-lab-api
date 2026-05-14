# tbx-lab-xhs

特别想-Lab 小红书内容智能发布平台。

这是独立微信云托管服务，不属于 `tbx-lab-admin` 小程序后台管理系统。

## 功能

- 热点标题采集
- 标题勾选入池
- 腾讯混元生成小红书笔记
- 红线扫描
- 图文方案
- 小红书发布预览
- 发布素材包导出

## 环境变量

见 `.env.example`。

正式环境必须配置 `HUNYUAN_API_KEY`。

## 启动

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 80
```

## 云托管

使用本目录 `Dockerfile` 部署为新服务 `tbx-lab-xhs`。
