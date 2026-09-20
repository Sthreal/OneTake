# One Take MVP

One Take 商品 AI 视频生成 MVP 的工程仓库。

## 当前阶段

当前为 **M1-16A：有人视频 Wan S2V 真实适配**。

已具备：

- React + TypeScript 响应式工作台
- FastAPI API、RQ Worker、PostgreSQL、Redis、MinIO
- Project、Asset、Outbox、Recognition、Image Edit、Matting、Main Image、Script、Provider 模块
- 项目创建、素材预签名、复核、列表和项目切换
- Mock 商品识别与人工确认
- Qwen-VL-Plus 商品识别 Adapter、严格候选 ID 校验和多图预处理
- Qwen Image Edit、Photoroom 和阿里云 SegmentCommodity 去背 Adapter
- Qwen-VL-Plus 文案视觉输入、严格 JSON 解析和事实数字校验
- CosyVoice V2 配音、音色/语速/语言设置和音频试听
- Wan S2V 有人视频 Adapter（默认 Mock；真实烟测待预算恢复）
- 字幕时间轴、SRT 生成、字幕编辑和编辑后重新配音
- 有人/无人两种视频模式与 3 个无人模板
- 视频方案、生成进度、成片预览与 MP4 下载
- 1080×1920、18–25 秒、30 fps、H.264/AAC 和 30 MB 成片卡口
- 内置 ffmpeg Mock 成片，不依赖系统 apt 或字体包
- Composition Port 隔离本地 Mock 与 Shotstack Stage
- Shotstack Ingest 直传素材、Render 异步轮询和成片回存 MinIO
- Noto Sans SC 本地烧录中文字幕，避免云端字体缺失或不一致
- 输出语音、输出字幕两个独立开关
- 项目媒体立即删除 API、24 小时过期媒体清理和 maintenance 队列
- Provider 配置预检、图片响应校验、透明 PNG 校验和失败隔离
- 主图处理 Pipeline：图像编辑 → 智能去背 → Pillow 标准化 → 人工确认
- 文案处理 Pipeline：事实校验 → Qwen-VL-Plus Port → 结构化文案 → 编辑确认
- 按能力独立配置 Provider 模式
- `MOCK_PROVIDERS` 全局安全锁，锁定后所有能力强制 Mock
- `GET /api/v1/providers/status` 查看配置状态，不返回密钥
- 苹果风三栏工作台、四段流程进度和最近项目恢复

默认启用 Mock Provider，不调用任何付费 AI 接口。真实 Qwen Recognition、Qwen Image Edit、Photoroom、阿里云 SegmentCommodity、Qwen-VL-Plus Script Adapter 和 Wan S2V Adapter 已接入代码，但必须显式关闭 Mock 安全锁、指定对应能力并配置凭据后才会启用；真实自动测试不会产生 API 费用。

## Provider 配置

```env
MOCK_PROVIDERS=true
RECOGNITION_PROVIDER=mock
IMAGE_EDIT_PROVIDER=mock
MATTING_PROVIDER=mock
SCRIPT_PROVIDER=mock
AVATAR_VIDEO_PROVIDER=mock
WAN_S2V_MODEL=
WAN_S2V_RESOLUTION=720P
WAN_S2V_MAX_SECONDS=30
WAN_S2V_PRICE_PER_SECOND=
WAN_S2V_AVATAR_PATH=
PROJECT_TTL_HOURS=24
MEDIA_CLEANUP_INTERVAL_SECONDS=3600
```

启用真实图像链路示例：

```env
MOCK_PROVIDERS=false
RECOGNITION_PROVIDER=real
IMAGE_EDIT_PROVIDER=real
MATTING_PROVIDER=aliyun
SCRIPT_PROVIDER=real
SCRIPT_MODEL=qwen-vl-plus
DASHSCOPE_API_KEY=your_key
ALIBABA_CLOUD_ACCESS_KEY_ID=your_access_key_id
ALIBABA_CLOUD_ACCESS_KEY_SECRET=your_access_key_secret
ALIBABA_CLOUD_REGION_ID=cn-shanghai
ALIYUN_IMAGESEG_ENDPOINT=imageseg.cn-shanghai.aliyuncs.com
```

有人模式真实 Provider 需要同时配置 `DASHSCOPE_API_KEY`、`WAN_S2V_MODEL` 和 `WAN_S2V_AVATAR_PATH`；仓库不内置真人人像素材。

真实 Provider 失败不会自动回退 Mock，避免将 Mock 结果误认为真实结果。
Shotstack 使用 Stage 时成片带水印，仅用于开发和联调；Production 阶段再切换 `SHOTSTACK_ENV=v1`。

## 启动

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

访问：

- Web: http://localhost:5173
- API: http://localhost:8000/docs
- Provider 状态: http://localhost:8000/api/v1/providers/status
- MinIO Console: http://localhost:9001

## 测试

后端：

```powershell
docker compose exec -T api pytest -q
```

前端：

```powershell
cd apps/web
npm run test:run
npm run build
```

## 页面流程

```text
填写商品名称
→ 创建项目
→ 上传并复核素材
→ 开始识别
→ 用户确认候选商品
→ 生成并确认主图
→ 补充事实并生成、编辑、确认文案
→ 生成、试听并确认配音
→ 编辑并确认字幕
→ 选择视频模式与无人模板
→ Mock 生成、预览并下载 MP4
→ Pipeline 进入 completed
```

## 架构与方案

- [架构设计](docs/架构设计.md)
- [方案档案](docs/方案档案.md)
