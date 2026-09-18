import { useEffect, useState } from "react";

import { FlowProgress } from "./FlowProgress";
import { ProjectRail } from "./ProjectRail";
import { SubtitlePanel } from "../audio-subtitle/SubtitlePanel";
import { useSubtitle } from "../audio-subtitle/useSubtitle";
import { VoicePanel } from "../audio-subtitle/VoicePanel";
import { useVoice } from "../audio-subtitle/useVoice";
import { MainImagePanel } from "../main-image/MainImagePanel";
import { ScriptPanel } from "../script/ScriptPanel";
import { useMainImage } from "../main-image/useMainImage";
import { useScript } from "../script/useScript";
import { RecognitionPanel } from "../recognition/RecognitionPanel";
import { useRecognition } from "../recognition/useRecognition";
import { VideoPanel } from "../video/VideoPanel";
import { useVideo } from "../video/useVideo";
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
    updateProject,
    selectProject,
    startNewProject,
  } = useProjectWorkspace();
  const uploads = useAssetUploads(project?.project_id ?? null);
  const recognition = useRecognition(project?.project_id ?? null);
  const mainImage = useMainImage(project?.project_id ?? null);
  const script = useScript(project?.project_id ?? null);
  const voice = useVoice(project?.project_id ?? null);
  const subtitle = useSubtitle(project?.project_id ?? null);
  const video = useVideo(project?.project_id ?? null);
  const [productName, setProductName] = useState("");
  const [productNote, setProductNote] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [copiedProjectId, setCopiedProjectId] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [draftProductName, setDraftProductName] = useState("");
  const [draftProductNote, setDraftProductNote] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (project) {
      setProductName(project.product_name);
      setProductNote(project.product_note ?? "");
      setDraftProductName(project.product_name);
      setDraftProductNote(project.product_note ?? "");
    }
    setCopiedProjectId(false);
    setIsEditing(false);
    setSaveError(null);
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

  function startEditing() {
    if (!project) return;
    setDraftProductName(project.product_name);
    setDraftProductNote(project.product_note ?? "");
    setSaveError(null);
    setIsEditing(true);
  }

  function cancelEditing() {
    if (!project) return;
    setDraftProductName(project.product_name);
    setDraftProductNote(project.product_note ?? "");
    setSaveError(null);
    setIsEditing(false);
  }

  async function saveProjectInfo() {
    if (!project) return;
    if (!draftProductName.trim()) {
      setSaveError("商品名称不能为空");
      return;
    }
    setIsSaving(true);
    setSaveError(null);
    try {
      await updateProject(project.project_id, draftProductName, draftProductNote);
      setIsEditing(false);
    } catch (requestError) {
      setSaveError(requestError instanceof Error ? requestError.message : "保存失败");
    } finally {
      setIsSaving(false);
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

      <FlowProgress currentStep={video.pipeline?.current_step ?? subtitle.pipeline?.current_step ?? voice.pipeline?.current_step ?? script.pipeline?.current_step ?? mainImage.pipeline?.current_step ?? recognition.pipeline?.current_step ?? 1} />

      <div className="workspace">
        <ProjectRail
          projects={projects}
          selectedProjectId={project?.project_id ?? null}
          isLoading={isLoadingProjects}
          onSelect={(projectId) => void selectProject(projectId)}
          onNew={startNewProject}
        />

        <main className="main-content">
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
                    <p>{isEditing ? "编辑后点击保存，项目列表会同步更新。" : "当前项目的商品名称、补充说明和项目标识。"}</p>
                  </div>
                  {isEditing ? (
                    <span className="inline-actions compact-actions">
                      <button className="button button-secondary" type="button" onClick={cancelEditing} disabled={isSaving}>取消</button>
                      <button className="button button-primary" type="button" onClick={() => void saveProjectInfo()} disabled={isSaving}>
                        {isSaving ? "保存中…" : "保存"}
                      </button>
                    </span>
                  ) : (
                    <button className="button button-secondary" type="button" onClick={startEditing}>编辑</button>
                  )}
                </div>
                {isEditing ? (
                  <div className="project-edit-grid">
                    <label className="field compact-field">
                      <span>商品名称 <em>必填</em></span>
                      <input value={draftProductName} onChange={(event) => setDraftProductName(event.target.value)} maxLength={80} />
                    </label>
                    <label className="field compact-field">
                      <span>补充说明 <small>可选</small></span>
                      <textarea value={draftProductNote} onChange={(event) => setDraftProductNote(event.target.value)} maxLength={240} rows={3} />
                    </label>
                    {saveError ? <div className="inline-error">{saveError}</div> : null}
                  </div>
                ) : (
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
                )}
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

              <RecognitionPanel
                state={recognition.recognition}
                readyAssetCount={uploads.readyCount}
                isStarting={recognition.isStarting}
                isConfirming={recognition.isConfirming}
                error={recognition.error}
                onStart={() => void recognition.start()}
                onConfirm={(assetId, candidateId) => void recognition.confirm(assetId, candidateId)}
              />

              {recognition.recognition.run?.status === "confirmed" || mainImage.state.version ? (
                <MainImagePanel
                  state={mainImage.state}
                  canStart={recognition.recognition.run?.status === "confirmed"}
                  isStarting={mainImage.isStarting}
                  isConfirming={mainImage.isConfirming}
                  error={mainImage.error}
                  onStart={() => void mainImage.start()}
                  onConfirm={() => void mainImage.confirm()}
                />
              ) : null}

              {mainImage.state.version?.status === "confirmed" || script.state.version ? (
                <ScriptPanel
                  state={script.state}
                  canStart={mainImage.state.version?.status === "confirmed"}
                  isStarting={script.isStarting}
                  isSaving={script.isSaving}
                  isConfirming={script.isConfirming}
                  error={script.error}
                  onStart={(input) => void script.start(input)}
                  onSave={(input) => void script.save(input)}
                  onConfirm={() => void script.confirm()}
                />
              ) : null}

              {script.state.version?.status === "confirmed" || voice.state.run ? (
                <VoicePanel
                  state={voice.state}
                  canStart={script.state.version?.status === "confirmed"}
                  isStarting={voice.isStarting}
                  error={voice.error}
                  onStart={(input) => void voice.start(input)}
                />
              ) : null}

              {voice.state.run?.status === "ready" || voice.state.run?.status === "confirmed" || subtitle.state.version ? (
                <SubtitlePanel
                  state={subtitle.state}
                  canStart={voice.state.run?.status === "ready" || voice.state.run?.status === "confirmed"}
                  isSaving={subtitle.isSaving}
                  isConfirming={subtitle.isConfirming}
                  error={subtitle.error}
                  onSave={(segments) => void subtitle.save(segments)}
                  onConfirm={() => void subtitle.confirm()}
                />
              ) : null}

              {subtitle.pipeline?.status === "audio_subtitle_confirmed" || subtitle.state.version?.status === "confirmed" || video.state.plan ? (
                <VideoPanel
                  state={video.state}
                  output={video.output}
                  canStart={subtitle.pipeline?.status === "audio_subtitle_confirmed" || subtitle.state.version?.status === "confirmed"}
                  voiceEnabled={voice.state.run?.enabled ?? true}
                  subtitleEnabled={subtitle.state.version?.enabled ?? true}
                  isStarting={video.isStarting}
                  error={video.error}
                  onGenerate={(mode, templateId) => void video.generate(mode, templateId)}
                />
              ) : null}

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
            <p>当前已贯通素材、主图、文案、配音、字幕和 Mock 成片。Wan 与 Shotstack 将在下一阶段接入。</p>
          </section>
        </aside>
      </div>
    </div>
  );
}
