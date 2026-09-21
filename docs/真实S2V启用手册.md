# One Take 真实 Wan S2V 启用手册

- 适用阶段：预算和合规人物素材准备完成后
- 默认状态：暂停，不执行真实付费烟测

## 一、前置条件

1. 百炼账户余额可用
2. 已确认实际 S2V 模型名
3. 已有合规人物素材
4. 人物素材为高清原图，不是低分辨率截图
5. 已确认肖像权、AI 合成、商业使用和第三方模型上传授权

## 二、人物素材要求

- 正面或轻微侧脸
- 头部完整，无遮挡
- 半身或全身
- 背景干净
- 光线均匀
- 图片清晰，短边建议至少 720px
- 不包含浏览器界面、水印或无关文字

## 三、环境变量

在 `.env` 中配置：

```env
MOCK_PROVIDERS=false
AVATAR_VIDEO_PROVIDER=real
WAN_S2V_MODEL=百炼控制台中的实际模型名
WAN_S2V_RESOLUTION=720P
WAN_S2V_MAX_SECONDS=30
WAN_S2V_PRICE_PER_SECOND=百炼控制台的实际单价
WAN_S2V_AVATAR_PATH=/app/src/onetake_api/assets/avatar/实际人物文件.png
DASHSCOPE_API_KEY=你的百炼Key
```

不要把 Key 写进 Git 或聊天记录。

## 四、烟测步骤

1. 将人物文件放入 `apps/api/src/onetake_api/assets/avatar/`
2. 修改 `.env` 并重启 `api`、`worker`
3. 运行完整 Mock 前置流程，确认配音和字幕已确认
4. 只创建一个 5 秒或最短可用时长的有人视频
5. 检查人物、口型、商品图层、音频和字幕
6. 通过后再运行 18–25 秒正式成片

## 五、失败回退

任何真实调用失败后：

```env
MOCK_PROVIDERS=true
AVATAR_VIDEO_PROVIDER=mock
```

然后重启 `api`、`worker`，恢复到零付费模式。

## 六、验收点

- 人物图像清晰，不发生明显身份漂移
- 口型与 CosyVoice 音频基本同步
- 原商品文字、Logo 和包装不变形
- 商品图层位置合理
- 输出为 9:16、1080×1920、30 fps、H.264/AAC
- 失败时不会产生 completed 成片