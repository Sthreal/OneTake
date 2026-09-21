# One Take 真实 Wan S2V 启用手册

- 适用阶段：预算和合规人物素材准备完成后
- 当前状态：2 秒真实烟测已通过；18–25 秒正式成片待验证

## 一、重要结论

`wan2.2-s2v-detect` 和 `wan2.2-s2v` 都可以通过 MaaS HTTP API 调用：

```text
Base URL：https://maas.qianwenaiapi.com
检测接口：/api/v1/services/aigc/image2video/face-detect
生成接口：/api/v1/services/aigc/image2video/video-synthesis
任务查询：/api/v1/tasks/{task_id}
```

图片检测：

```json
{
  "model": "wan2.2-s2v-detect",
  "input": {
    "image_url": "https://你的公网可读图片地址"
  }
}
```

提交生成任务时必须带：

```text
X-DashScope-Async: enable
```

生成结果不在 `output.video_url`，而在：

```text
output.results.video_url
```

## 二、前置条件

1. 百炼账户余额可用
2. 已确认实际 S2V 模型名为 `wan2.2-s2v`
3. 已有合规人物素材
4. 人物素材为高清原图或高质量裁切图
5. 已确认肖像权、AI 合成、商业使用和第三方模型上传授权

## 三、人物素材要求

- 正面或轻微侧脸
- 头部完整，无遮挡
- 半身或全身
- 背景干净
- 光线均匀
- 图片清晰，短边至少 720px
- 推荐 720×1280 或 1080×1920 的 9:16 图
- 不包含浏览器界面、水印或无关文字

## 四、环境变量

在 `.env` 中配置：

```env
MOCK_PROVIDERS=false
AVATAR_VIDEO_PROVIDER=real
WAN_S2V_MODEL=wan2.2-s2v
WAN_S2V_RESOLUTION=720P
WAN_S2V_MAX_SECONDS=30
WAN_S2V_PRICE_PER_SECOND=0.9
WAN_S2V_AVATAR_PATH=/app/src/onetake_api/assets/avatar/high-res-avatar-9x16.png
DASHSCOPE_API_KEY=你的百炼Key
```

修改后必须重启 `api` 和 `worker`。不要把 Key 写进 Git 或聊天记录。

## 五、临时素材上传

项目使用 `DashScopeTemporaryUploader` 上传图片和音频，返回 `oss://` 地址。此时请求必须增加：

```text
X-DashScope-OssResourceResolve: enable
```

缺少该请求头时，MaaS 会返回：

```text
InvalidParameter.DataInspection
The media format is not supported or incorrect for the data inspection.
```

## 六、生成请求

```json
{
  "model": "wan2.2-s2v",
  "input": {
    "image_url": "oss://...",
    "audio_url": "oss://...",
    "prompt": "固定数字人正面对镜口播"
  },
  "parameters": {
    "resolution": "720P",
    "duration": 2,
    "prompt_extend": false,
    "watermark": false
  }
}
```

请求头：

```text
Authorization: Bearer <DASHSCOPE_API_KEY>
Content-Type: application/json
X-DashScope-Async: enable
X-DashScope-OssResourceResolve: enable
```

## 七、费用

| 输出 | 单价 | 2 秒烟测 | 5 秒烟测 | 18 秒成片 |
|---|---:|---:|---:|---:|
| 480P | 0.5 元/秒 | 约 1.0 元 | 约 2.5 元 | 约 9.0 元 |
| 720P | 0.9 元/秒 | 约 1.8 元 | 约 4.5 元 | 约 16.2 元 |

Shotstack 合成和真实配音费用另计。

## 八、烟测步骤

1. 将人物文件放入 `apps/api/src/onetake_api/assets/avatar/`
2. 配置 `.env` 并重启 `api`、`worker`
3. 先调用 `wan2.2-s2v-detect` 确认素材通过检测
4. 使用 2 秒级音频跑 `wan2.2-s2v`
5. 轮询任务，成功后从 `output.results.video_url` 下载成片
6. 检查人物、口型、音频和输出比例
7. 通过后再跑 18–25 秒正式成片
8. 不直接跑 18 秒作为第一次真实调用

## 九、已验证记录

- 检测通过的 9:16 人物图：720×1280
- 2 秒 Adapter 烟测任务：`9a8cbe0f-f535-4b43-88e3-0230d8cadbf2`
- 输出规格：720×1280，9:16
- 成片已回存 MinIO，未重复计费
- 后端全量测试：152 passed

## 十、失败回退

任何真实调用失败后：

```env
MOCK_PROVIDERS=true
AVATAR_VIDEO_PROVIDER=mock
```

然后重启 `api`、`worker`，恢复到零付费模式。

## 十一、验收点

- 人物图像清晰，不发生明显身份漂移
- 口型与 CosyVoice 音频基本同步
- 原商品文字、Logo 和包装不变形
- 商品图层位置合理
- 输出为 9:16
- 失败时不会产生 completed 成片
