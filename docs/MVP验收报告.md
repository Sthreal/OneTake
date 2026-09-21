# One Take MVP 验收报告

- 日期：2026-09-21
- 当前阶段：M1-16D
- 默认运行模式：Mock Provider
- 真实付费烟测：暂停

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

### 数据生命周期

- 项目媒体立即删除 API：`DELETE /api/v1/projects/{project_id}/media`
- MinIO 支持单对象删除和项目前缀删除
- maintenance 队列每小时清理过期媒体
- 过期项目只删除媒体对象，保留项目、流程和审计记录
- 本地清理任务已执行验证

### Provider 安全

- `.env` 默认保持 `MOCK_PROVIDERS=true`
- 未调用真实付费 API
- Provider 状态接口可查看 effective provider

## 二、未验证

以下能力代码已接入或已有方案，但没有执行真实付费验收：

- 真实 Wan S2V 有人视频
- 真实 Wan 2.6 I2V 商品视频画质
- 真实 Shotstack Production 成片
- 真实 Qwen Image Edit / Qwen-VL / CosyVoice 全链路

## 三、已知限制

- 当前人物头像已居中裁切为 720×1280，可用于 Mock；正式 S2V 仍需通过 wan2.2-s2v-detect 检测
- 真实 S2V 需要高清合规人物素材和百炼余额
- 真实商品视频画质尚未经用户确认真实成片
- Seedance 未接入
- 没有账号体系、云端历史、收款和批量生产

## 四、自动验收命令

```powershell
$env:Path='E:\DockerDesktop\resources\bin;'+$env:Path

docker compose exec -T api pytest -q
docker compose exec -T web npm test -- --run
docker compose exec -T web npm run build
python scripts/mock_e2e.py
```

## 五、结论

当前 MVP 的 Mock P0 主链路已经闭环。代码侧可以冻结，等待预算和合规人物素材后再进入真实 S2V 验收。