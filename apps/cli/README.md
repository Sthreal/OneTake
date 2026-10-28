# One Take CLI（批次 7）

把 One Take 的**既有 HTTP 端点**包成命令行 —— **不重写任何业务逻辑**：
能不能下载、要不要审批、费用多少，全部来自服务端字段。

## 安装 / 运行

零依赖（只用 Python 标准库）：

```bash
# 直接跑（仓库内）
PYTHONPATH=apps/cli/src python -m onetake_cli.main --base-url http://localhost:8000 project list

# 或者装成本地命令
pip install -e apps/cli     # 之后可直接用 `onetake`
```

服务端地址默认 `http://localhost:8000`，可用 `--base-url` 或环境变量 `ONETAKE_BASE_URL` 覆盖。

## 命令

| 命令 | 作用 | 打的端点 |
|---|---|---|
| `project create --name X [--note Y]` | 建项目 | `POST /api/v1/projects` |
| `project list` / `project show <pid>` | 列表 / 查看 | `GET /api/v1/projects[/{pid}]` |
| `recognize <pid> [--confirm]` | 商品识别（可顺带确认） | `POST …/recognition`（+ `…/{run}/confirm`） |
| `plan <pid> [--confirm]` | 内容方案（可顺带确认） | `POST …/content-plan`（+ `/confirm`） |
| `keyframes <pid> [--generate SCENE] [--accept-scene SCENE --candidate KF]` | 关键帧列表 / 生成 / 采用 | `GET/POST …/video/keyframes…` |
| `segments <pid> [--generate SEG] [--accept SEG] [--retake SEG --symptom X]` | 分段列表 / 生成 / 采用 / 定向返修 | `GET/POST …/video/segments…` |
| `compose <pid>` | 合成成片 | `POST …/compose` |
| `gate <pid> [--ack CHECK_ID]…` | 交付门结论（**未放行退出码 3**） | `GET …/video/gate`（+ `/ack`） |
| `export <pid> [--profiles] [--profile douyin] [--kind video\|cover] [--at 0.5]` | 多平台导出 | `GET …/export/profiles`、`POST …/export` |

## 退出码（便于接 CI / 定时任务）

| 码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | 用法/参数错误 |
| `2` | 服务端拒绝或调用失败（stderr 里带服务端 message） |
| `3` | **交付门未放行**（`download_allowed=false`） |

`--json` 输出原始响应（放在子命令前后都认）。

## 测试

CLI 的用例在 `apps/api/tests/integration/test_cli.py`：**同进程**把 FastAPI 的 TestClient 当传输层打真实端点
（不是 mock 服务端），并在最后一条用例里断言"非 ASCII 的 id 会被 URL 编码"（真机 `urllib` 上踩过）。

## 例子

```bash
onetake project create --name "口红测试"
onetake recognize "$PID" --confirm
onetake plan "$PID" --confirm
onetake keyframes "$PID" --json
onetake compose "$PID"
onetake gate "$PID" || echo "交付门没放行（退出码 $?）"
onetake export "$PID" --profile xiaohongshu --kind cover --at 0.5
```