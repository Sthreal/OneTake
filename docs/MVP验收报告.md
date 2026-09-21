# One Take MVP 验收报告

- 日期：2026-09-21
- 当前阶段：M1-16D.2
- 默认运行模式：Mock Provider
- 真实付费烟测：仅完成 2 秒 Wan S2V，其他真实链路暂停

## 一、已验证

### Mock 全流程

以下流程已经通过 `scripts/mock_e2e.py` 自动验证：

```text
创建项目
→ 上传商品图
→ 商品识别
→ 主图生成
→ 文案生成
→ 配音
→ 字幕
→ 内容分镜确认
→ 有人视频
→ clean 无人视频
→ dynamic 无人视频
→ lifestyle 无人视频
```

抽查结果：

- 输出规格：1080×1920、25 秒、30 fps、H.264、AAC
- 商品使用原始图层叠加
- Mock 有人模式使用本地人物占位头像
- 所有视频任务状态为 `completed`

### 真实 Wan S2V

已通过 MaaS HTTP API 完成 2 秒真实烟测：

- 输入人物图：720×1280、9:16
- 检测模型：`wan2.2-s2v-detect`，返回 `check_pass=true`
- 生成模型：`wan2.2-s2v`
- 输出规格：720×1280、9:16
- Adapter 任务：`9a8cbe0f-f535-4b43-88e3-0230d8cadbf2`
- 任务状态：`SUCCEEDED`
- 成片已回存 MinIO
- 提交使用 `X-DashScope-Async: enable`
- `oss://` 素材使用 `X-DashScope-OssResourceResolve: enable`
- 视频地址读取自 `output.results.video_url`

### 数据生命周期

- 项目媒体立即删除 API：`DELETE /api/v1/projects/{project_id}/media`
- MinIO 支持单对象删除和项目前缀删除
- maintenance 队列每小时清理过期媒体
- 过期项目只删除媒体对象，保留项目、流程和审计记录
- 本地清理任务已执行验证

## 二、真实 S2V 调用结论

之前使用 `dashscope.VideoSynthesis.async_call/wait` 会返回 `InvalidParameter url error`，该路径已经替换为 MaaS HTTP 异步调用。

正确链路：

```text
POST /api/v1/services/aigc/image2video/video-synthesis
→ 保存 output.task_id
→ GET /api/v1/tasks/{task_id}
→ 读取 output.results.video_url
→ 下载视频
```

仅使用 `X-DashScope-Async` 但缺少 `X-DashScope-OssResourceResolve` 时，`oss://` 素材会被判定为格式不支持。

## 三、未验证

- 18–25 秒真实 Wan S2V 正式成片
- 真实 S2V 与 Shotstack 商品图层、字幕的完整合成
- 真实 Wan 2.6 I2V 商品视频画质
- 真实 Shotstack Production 成片
- 真实 Qwen Image Edit / Qwen-VL / CosyVoice 全链路
- 用户对真实 2 秒烟测画面的视觉验收

## 四、已知限制

- 当前人物头像已居中裁切为 720×1280
- 正式 S2V 需要高清合规人物素材和百炼余额
- 真实 S2V 720P 约 0.9 元/秒
- 当前有效运行配置仍为 `MOCK_PROVIDERS=true`、`AVATAR_VIDEO_PROVIDER=mock`；UI 真实验证前需切换这两个开关并重建 `api`、`worker`
- 没有账号体系、云端历史、收款和批量生产

## 五、自动验收命令

```powershell
docker compose exec -T api pytest -q
docker compose exec -T web npm test -- --run
docker compose exec -T web npm run build
python scripts/mock_e2e.py
```

## 六、结论

Mock P0 主链路保持闭环；真实 Wan S2V Adapter 已通过 2 秒付费烟测。下一步是重启服务加载当前配置后，从工作台发起一次真实有人视频验证，再决定是否跑 18–25 秒正式成片。
