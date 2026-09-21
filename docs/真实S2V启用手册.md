# One Take 真实 Wan S2V 启用手册

- 适用阶段：预算和合规人物素材准备完成后
- 默认状态：暂停，不执行真实付费烟测

## 一、重要结论

`wan2.2-s2v-detect` 是 `wan2.2-s2v` 的辅助模型，官方页面仅提供模型信息和价格：

```text
图片检测：0.004 元/张
```

目前没有找到可公开单独调用的 `wan2.2-s2v-detect` API 示例。不要把“单独跑 detect”作为真实链路的前置步骤。

真实链路直接从最短 `wan2.2-s2v` 烟测开始，模型内部会处理图片预检查。

## 二、前置条件

1. 百炼账户余额可用
2. 已确认实际 S2V 模型名
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

不要把 Key 写进 Git 或聊天记录。

## 五、费用

| 输出 | 单价 | 2 秒烟测 | 5 秒烟测 | 18 秒成片 |
|---|---:|---:|---:|---:|
| 480P | 0.5 元/秒 | 约 1.0 元 | 约 2.5 元 | 约 9.0 元 |
| 720P | 0.9 元/秒 | 约 1.8 元 | 约 4.5 元 | 约 16.2 元 |

Shotstack 合成和真实配音费用另计。

## 六、烟测步骤

1. 将人物文件放入 `apps/api/src/onetake_api/assets/avatar/`
2. 修改 `.env` 并重启 `api`、`worker`
3. 先使用已确认的短音频或独立烟测脚本
4. 只跑 2 秒级 `wan2.2-s2v`
5. 检查人物、口型、商品图层、音频和字幕
6. 通过后再跑 18–25 秒正式成片
7. 不直接跑 18 秒作为第一次真实调用

## 七、失败回退

任何真实调用失败后：

```env
MOCK_PROVIDERS=true
AVATAR_VIDEO_PROVIDER=mock
```

然后重启 `api`、`worker`，恢复到零付费模式。

## 八、验收点

- 人物图像清晰，不发生明显身份漂移
- 口型与 CosyVoice 音频基本同步
- 原商品文字、Logo 和包装不变形
- 商品图层位置合理
- 输出为 9:16、1080×1920、30 fps、H.264/AAC
- 失败时不会产生 completed 成片