import { useEffect, useState } from "react";

type ServiceStatus = {
  ok: boolean;
  detail: string;
};

type HealthResponse = {
  status: "ok" | "degraded";
  stage: string;
  mock_providers: boolean;
  services: Record<string, ServiceStatus>;
};

const serviceNames: Record<string, string> = {
  postgres: "PostgreSQL",
  redis: "Redis",
  minio: "MinIO",
};

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function loadHealth() {
      try {
        const response = await fetch("/api/health");
        const data = (await response.json()) as HealthResponse;
        if (active) {
          setHealth(data);
          setError(null);
        }
      } catch (loadError) {
        if (active) {
          setError(loadError instanceof Error ? loadError.message : "无法连接 API");
        }
      }
    }

    loadHealth();
    const timer = window.setInterval(loadHealth, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">1T</span>
          <div>
            <strong>One Take</strong>
            <small>商品视频工作台</small>
          </div>
        </div>
        <span className="stage-chip">M0 · 工程骨架</span>
      </header>

      <section className="hero">
        <span className="eyebrow">MVP FOUNDATION</span>
        <h1>先跑通基础设施，再接真实 Provider。</h1>
        <p>
          当前版本只验证 Web、API、Worker、PostgreSQL、Redis 和 MinIO
          之间的连接。AI 与媒体能力全部保持 Mock。
        </p>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>运行状态</h2>
            <p>API 每 5 秒检查一次依赖服务。</p>
          </div>
          <span className={`health-badge ${health?.status === "ok" ? "is-ok" : "is-pending"}`}>
            {health?.status ?? "checking"}
          </span>
        </div>

        <div className="service-grid">
          {Object.entries(serviceNames).map(([key, label]) => {
            const service = health?.services[key];
            return (
              <article className="service-card" key={key}>
                <span className={`service-dot ${service?.ok ? "is-ok" : ""}`} />
                <strong>{label}</strong>
                <small>{service?.detail ?? "等待检查"}</small>
              </article>
            );
          })}
        </div>

        {error && <div className="error-box">{error}</div>}

        <dl className="facts">
          <div>
            <dt>Pipeline</dt>
            <dd>确定性状态机</dd>
          </div>
          <div>
            <dt>模块化</dt>
            <dd>一个概念一个模块</dd>
          </div>
          <div>
            <dt>付费接口</dt>
            <dd>默认关闭</dd>
          </div>
          <div>
            <dt>Provider</dt>
            <dd>Mock</dd>
          </div>
        </dl>
      </section>

      <footer>
        <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">
          API 文档
        </a>
        <a href="http://localhost:9001" target="_blank" rel="noreferrer">
          MinIO Console
        </a>
      </footer>
    </main>
  );
}