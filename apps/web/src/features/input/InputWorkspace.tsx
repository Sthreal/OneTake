import { useEffect, useState } from "react";

import { FlowProgress } from "./FlowProgress";
import { ProjectRail } from "./ProjectRail";
import { MAX_ASSETS_PER_PROJECT } from "./validation";
import { UploadAssetCard } from "./UploadAssetCard";
import { UploadDropzone } from "./UploadDropzone";
import { useAssetUploads } from "./useAssetUploads";
import { useProjectWorkspace } from "./useProjectWorkspace";

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <span />
      <span />
    </span>
  );
}

export function InputWorkspace() {
  const {
    projects,
    project,
    isLoadingProjects,
    isCreating,
    error,
    createProject,
    selectProject,
    startNewProject,
  } = useProjectWorkspace();
  const uploads = useAssetUploads(project?.project_id ?? null);
  const [productName, setProductName] = useState("");
  const [productNote, setProductNote] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [copiedProjectId, setCopiedProjectId] = useState(false);

  useEffect(() => {
    if (project) {
      setProductName(project.product_name);
      setProductNote(project.product_note ?? "");
    }
    setCopiedProjectId(false);
  }, [project]);

  async function copyProjectId() {
    if (!project) return;
    try {
      await navigator.clipboard.writeText(project.project_id);
      setCopiedProjectId(true);
      window.setTimeout(() => setCopiedProjectId(false), 1500);
    } catch {
      setCopiedProjectId(false);
    }
  }

  async function handleCreateProject(event: React.FormEvent) {
    event.preventDefault();
    if (!productName.trim()) {
      setFormError("请填写商品名称");
      return;
    }
    setFormError(null);
    await createProject(productName, productNote).catch(() => undefined);
  }

  const uploadDisabled =
    !project || uploads.isBusy || uploads.validCount >= MAX_ASSETS_PER_PROJECT;
  const completionPercent = uploads.validCount
    ? Math.round((uploads.readyCount / uploads.validCount) * 100)
    : 0;

  return (
    <div className="app-frame">
      <header className="toolbar">
        <div className="toolbar-brand">
          <BrandMark />
          <div>
            <strong>One Take</strong>
            <span>商品视频工作台</span>
          </div>
        </div>
        <div className="toolbar-center">
          <span className="project-pill">
            {project ? project.product_name : "未选择项目"}
          </span>
        </div>
        <div className="toolbar-actions">
          <span className={"status-badge " + (project ? "is-active" : "")}>
            <i />
            {project ? "项目已保存" : "等待输入"}
          </span>
        </div>
      </header>

      <FlowProgress currentStep={1} />

      <div className="workspace">
        <ProjectRail
          projects={projects}
          selectedProjectId={project?.project_id ?? null}
          isLoading={isLoadingProjects}
          onSelect={(projectId) => void selectProject(projectId)}
          onNew={startNewProject}
        />

        <main className="main-content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">INPUT WORKSPACE</span>
              <h1>{project ? "准备商品素材" : "创建新的商品项目"}</h1>
              <p>
                {project
                  ? "上传 1–5 张同一商品的清晰图片，系统会完成文件复核并保存到 MinIO。"
                  : "填写商品名称并创建项目，之后可以随时从左侧项目列表切换回来。"}
              </p>
            </div>
            <span className="phase-chip">第 1 步 / 共 4 步</span>
          </div>

          {!project ? (
            <section className="surface-card project-card">
              <div className="section-heading">
                <div>
                  <h2>商品信息</h2>
                  <p>商品名称用于创建项目，补充说明可选。</p>
                </div>
              </div>
              <form onSubmit={handleCreateProject}>
                <div className="form-grid">
                  <label className="field">
                    <span>商品名称 <em>必填</em></span>
                    <input
                      value={productName}
                      onChange={(event) => setProductName(event.target.value)}
                      placeholder="例如：便携式榨汁杯"
                      maxLength={80}
                    />
                  </label>
                  <label className="field">
                    <span>补充说明 <small>可选</small></span>
                    <textarea
                      value={productNote}
                      onChange={(event) => setProductNote(event.target.value)}
                      placeholder="例如：白色杯身，包装上带有品牌文字"
                      maxLength={240}
                      rows={3}
                    />
                  </label>
                </div>
                {formError || error ? <div className="inline-error">{formError ?? error}</div> : null}
                <div className="form-actions">
                  <span>创建后会自动加入左侧项目列表。</span>
                  <button className="button button-primary" type="submit" disabled={isCreating}>
                    {isCreating ? "正在创建…" : "创建项目"}
                  </button>
                </div>
              </form>
            </section>
          ) : (
            <>
              <section className="surface-card project-card">
                <div className="section-heading">
                  <div>
                    <h2>商品信息</h2>
                    <p>当前项目的商品名称、补充说明和项目标识。</p>
                  </div>
                  <span className="saved-indicator">已保存</span>
                </div>
                <div className="project-info-grid">
                  <div className="project-info-item project-info-primary">
                    <span>商品名称</span>
                    <strong>{project.product_name}</strong>
                  </div>
                  <div className="project-info-item">
                    <span>补充说明</span>
                    <p>{project.product_note || "暂无"}</p>
                  </div>
                  <div className="project-id-row">
                    <span>项目 ID</span>
                    <code>{project.project_id}</code>
                    <button className="copy-button" type="button" onClick={() => void copyProjectId()}>
                      {copiedProjectId ? "已复制" : "复制"}
                    </button>
                  </div>
                </div>
              </section>

              <section className="surface-card upload-section">
                <div className="section-heading">
                  <div>
                    <h2>商品图片</h2>
                    <p>支持 JPG、PNG、WebP，单图不超过 10 MB。</p>
                  </div>
                  <span className="count-chip">{uploads.validCount} / {MAX_ASSETS_PER_PROJECT}</span>
                </div>
                <UploadDropzone disabled={uploadDisabled} onFiles={(files) => void uploads.addFiles(files)} />
                {uploads.notice ? <div className="inline-notice">{uploads.notice}</div> : null}
                <div className="upload-actions">
                  <div>
                    <strong>{uploads.readyCount} 张已完成</strong>
                    <span>{uploads.isBusy ? "正在处理图片…" : "失败文件可单独重试"}</span>
                  </div>
                  <button
                    className="button button-primary"
                    type="button"
                    disabled={!uploads.hasQueued || uploads.isBusy}
                    onClick={() => void uploads.startUploads()}
                  >
                    上传素材
                  </button>
                </div>
              </section>

              <section className="surface-card asset-section">
                <div className="section-heading">
                  <div>
                    <h2>素材队列</h2>
                    <p>每张图片独立校验、上传和复核。</p>
                  </div>
                  <span className="count-chip">{uploads.items.length} 张</span>
                </div>
                {uploads.isLoadingAssets ? (
                  <div className="empty-state compact"><span className="spinner" />读取素材中…</div>
                ) : uploads.items.length ? (
                  <div className="asset-list">
                    {uploads.items.map((item) => (
                      <UploadAssetCard
                        key={item.localId}
                        item={item}
                        onRetry={(localId) => void uploads.retryItem(localId)}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="empty-state compact">
                    <strong>还没有图片</strong>
                    <p>拖拽商品图到上方区域开始。</p>
                  </div>
                )}
              </section>
            </>
          )}
        </main>

        <aside className="inspector">
          <section className="inspector-card project-summary">
            <div className="inspector-heading"><span>当前项目</span><span className="live-dot" /></div>
            <strong>{project?.product_name ?? "尚未选择"}</strong>
            <p>{project?.project_id ?? "从左侧选择项目或创建新项目"}</p>
            <div className="progress-block">
              <div><span>素材完成度</span><strong>{completionPercent}%</strong></div>
              <div className="progress-track"><span style={{ width: completionPercent + "%" }} /></div>
            </div>
          </section>

          <section className="inspector-card">
            <div className="inspector-heading"><span>上传规则</span><span>固定</span></div>
            <ul className="rule-list">
              <li><span>格式</span><strong>JPG / PNG / WebP</strong></li>
              <li><span>数量</span><strong>最多 5 张</strong></li>
              <li><span>大小</span><strong>≤ 10 MB</strong></li>
              <li><span>短边</span><strong>≥ 512 px</strong></li>
              <li><span>比例</span><strong>1:5–5:1</strong></li>
            </ul>
          </section>

          <section className="inspector-card soft-card">
            <strong>当前边界</strong>
            <p>本阶段只验证素材输入和 MinIO 直传。识别、主图和视频生成将在后续切片接入。</p>
          </section>
        </aside>
      </div>
    </div>
  );
}