"""商品 URL 抓取适配层（S13）。

分层：`guard`（SSRF 防护，纯函数）→ `fetcher`（httpx 拉页面，限大小/超时/跳转次数）
→ `parser`（OpenGraph → JSON-LD → 裸标签 三级回退）。抓到的结果立刻汇入**既有资产链路**，
不产生第二条资产路径。
"""