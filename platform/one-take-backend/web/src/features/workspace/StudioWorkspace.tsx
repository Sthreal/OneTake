import { useEffect, useState, type FormEvent } from "react";

import { AgentDock } from "../agent/AgentDock";
import { SubtitlePanel } from "../audio-subtitle/SubtitlePanel";
import { useSubtitle } from "../audio-subtitle/useSubtitle";
import { VoicePanel } from "../audio-subtitle/VoicePanel";
import { useVoice } from "../audio-subtitle/useVoice";
import { ContentPlanPanel } from "../content-plan/ContentPlanPanel";
import { useContentPlan } from "../content-plan/useContentPlan";
import { ContentQualityPanel } from "../content-quality/ContentQualityPanel";
import { useContentQuality } from "../content-quality/useContentQuality";
import { ProjectRail } from "../input/ProjectRail";
import { UploadAssetCard } from "../input/UploadAssetCard";
import { UploadDropzone } from "../input/UploadDropzone";
import { useAssetUploads } from "../input/useAssetUploads";
import { useProjectWorkspace } from "../input/useProjectWorkspace";
import { MAX_ASSETS_PER_PROJECT } from "../input/validation";
import { WorkspaceStageNav } from "../input/WorkspaceStageNav";
import {
  WORKSPACE_STAGES,
  deriveWorkspaceStage,
  type WorkspaceStageId,
} from "../input/workspaceStages";
import { MainImagePanel } from "../main-image/MainImagePanel";
import { useMainImage } from "../main-image/useMainImage";
import { RecognitionPanel } from "../recognition/RecognitionPanel";
import { useRecognition } from "../recognition/useRecognition";
import { ScriptPanel } from "../script/ScriptPanel";
import { useScript } from "../script/useScript";
import { Icon } from "../../shared/ui/Icon";
import { VideoPanel } from "../video/VideoPanel";
import { useVideo } from "../video/useVideo";

type StageThreeTab = "main" | "script" | "quality";

interface InspectorItem {
  label: string;
  detail: string;
  state: "done" | "current" | "pending";
}

function BrandMark() {
  return (
    <span className="simplified-logo" aria-hidden="true">
      <i />
      <i />
    </span>
  );
}

function formatWorkspaceStatus(status: string | null): string {
  const labels: Record<string, string> = {
    assets_ready: "素材已就绪",
    recognizing: "正在识别商品",
    recognition_ready: "识别结果待确认",
    recognition_confirmed: "商品识别已确认",
    main_image_queued: "主图任务已排队",
    image_editing: "正在处理主图",
    matting: "正在抠图",
    main_image_ready: "主图待确认",
    main_image_confirmed: "主图已确认",
    script_queued: "文案任务已排队",
    script_generating: "正在生成文案",
    script_ready: "文案待确认",
    script_confirmed: "文案已确认",
    voice_queued: "配音任务已排队",
    voice_generating: "正在生成配音",
    voice_ready: "配音待确认",
    subtitle_queued: "字幕任务已排队",
    subtitle_generating: "正在生成字幕",
    subtitle_ready: "字幕待确认",
    audio_subtitle_confirmed: "配音字幕已确认",
    content_plan_ready: "分镜待确认",
    content_plan_confirmed: "分镜已确认",
    content_qa_passed: "内容质检通过",
    content_qa_failed: "内容质检未通过",
    video_plan_ready: "视频方案待确认",
    video_generating: "正在生成视频",
    video_ready: "视频待合成",
    rendering: "正在合成成片",
    completed: "成片已完成",
    failed: "当前阶段执行失败",
  };
  return status ? labels[status] ?? status : "等待开始";
}

export function StudioWorkspace() {
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
  const contentPlan = useContentPlan(project?.project_id ?? null);
  const contentQuality = useContentQuality(project?.project_id ?? null);
  const video = useVideo(project?.project_id ?? null);

  const [stageView, setStageView] = useState<WorkspaceStageId | null>(null);
  const [stageThreeTab, setStageThreeTab] = useState<StageThreeTab>("main");
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

  useEffect(() => {
    setStageView(null);
    setStageThreeTab("main");
  }, [project?.project_id]);

  const pipeline =
    video.pipeline ??
    subtitle.pipeline ??
    voice.pipeline ??
    script.pipeline ??
    mainImage.pipeline ??
    recognition.pipeline;
  const currentStage = deriveWorkspaceStage({
    hasProject: Boolean(project),
    readyAssetCount: uploads.readyCount,
    pipelineStatus: pipeline?.status ?? null,
    currentStep: pipeline?.current_step ?? null,
    recognitionStatus: recognition.recognition.run?.status ?? null,
    hasMainImage: Boolean(mainImage.state.version),
    scriptStatus: script.state.version?.status ?? null,
    hasVoice: Boolean(voice.state.run),
    hasSubtitle: Boolean(subtitle.state.version),
    hasContentPlan: Boolean(contentPlan.plan),
    hasVideoPlan: Boolean(video.state.plan),
  });
  const activeStage = Math.min(stageView ?? currentStage, currentStage) as WorkspaceStageId;
  const activeStageDefinition = WORKSPACE_STAGES.find((stage) => stage.id === activeStage) ?? WORKSPACE_STAGES[0];

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

  async function handleCreateProject(event: FormEvent) {
    event.preventDefault();
    if (!productName.trim()) {
      setFormError("请填写商品名称");
      return;
    }
    setFormError(null);
    await createProject(productName, productNote).catch(() => undefined);
  }

  const uploadDisabled = !project || uploads.isBusy || uploads.validCount >= MAX_ASSETS_PER_PROJECT;
  const recognitionConfirmed = recognition.recognition.run?.status === "confirmed";
  const mainImageConfirmed = mainImage.state.version?.status === "confirmed";
  const scriptConfirmed = script.state.version?.status === "confirmed";
  const voiceReady = voice.state.run?.status === "ready" || voice.state.run?.status === "confirmed";
  const subtitleConfirmed = subtitle.state.version?.status === "confirmed";
  const hasOutput = Boolean(video.output);

  const inspectorItems: InspectorItem[] = activeStage === 1
    ? [
        { label: "项目信息", detail: project ? project.product_name : "等待创建项目", state: project ? "done" : "current" },
        { label: "商品图片", detail: `${uploads.readyCount} / ${MAX_ASSETS_PER_PROJECT} 张已完成`, state: uploads.readyCount > 0 ? "done" : "current" },
      ]
    : activeStage === 2
      ? [
          { label: "素材准备", detail: `${uploads.readyCount} 张图片可用`, state: uploads.readyCount > 0 ? "done" : "current" },
          { label: "商品主体", detail: recognitionConfirmed ? "识别结果已确认" : "等待识别与确认", state: recognitionConfirmed ? "done" : "current" },
        ]
      : activeStage === 3
        ? [
            { label: "商品识别", detail: recognitionConfirmed ? "商品主体已确认" : "前置步骤未完成", state: recognitionConfirmed ? "done" : "pending" },
            { label: "主图处理", detail: mainImageConfirmed ? "主图版本已确认" : "等待生成并确认主图", state: mainImageConfirmed ? "done" : "current" },
            { label: "口播文案", detail: scriptConfirmed ? "文案已确认" : "等待编辑并确认文案", state: scriptConfirmed ? "done" : "current" },
          ]
        : activeStage === 4
          ? [
              { label: "配音", detail: voiceReady ? "配音已生成" : "等待生成配音", state: voiceReady ? "done" : "current" },
              { label: "字幕", detail: subtitleConfirmed ? "字幕已确认" : "等待字幕确认", state: subtitleConfirmed ? "done" : "current" },
              { label: "视频分镜", detail: contentPlan.plan?.status === "confirmed" ? "分镜已确认" : "等待生成分镜", state: contentPlan.plan?.status === "confirmed" ? "done" : "current" },
            ]
          : [
              { label: "音频字幕", detail: subtitleConfirmed ? "字幕已确认" : "前置步骤未完成", state: subtitleConfirmed ? "done" : "pending" },
              { label: "视频方案", detail: video.state.plan ? formatWorkspaceStatus(video.state.plan.status) : "等待生成视频", state: video.state.plan?.status === "completed" ? "done" : "current" },
              { label: "成片输出", detail: hasOutput ? "MP4 已生成，可预览和下载" : "等待视频合成完成", state: hasOutput ? "done" : "current" },
            ];

  const pendingItem = inspectorItems.find((item) => item.state !== "done") ?? inspectorItems[inspectorItems.length - 1];

  return (
    <div className="simplified-shell onetake-workspace">
      <header className="simplified-topbar">
        <div className="simplified-brand">
          <BrandMark />
          <span><strong>ONE TAKE</strong><small>PRODUCTION DESK</small></span>
        </div>
        <div className="simplified-project-switcher">
          <span>{project?.product_name ?? "未选择项目"}</span>
          <small>{project ? `自动保存 · ${formatWorkspaceStatus(pipeline?.status ?? null)}` : "创建项目后开始生产"}</small>
          <Icon name="chevron" size={15} />
        </div>
        <div className="simplified-top-actions">
          <span className={`status-badge ${project ? "is-active" : ""}`}><i />{project ? "项目已保存" : "等待输入"}</span>          <button className="simplified-avatar" type="button" aria-label="账户菜单">徐</button>
        </div>
      </header>

      <WorkspaceStageNav activeStage={activeStage} currentStage={currentStage} onSelect={setStageView} />

      <div className="simplified-body">
        <aside className="project-sidebar">
          <ProjectRail
            projects={projects}
            selectedProjectId={project?.project_id ?? null}
            isLoading={isLoadingProjects}
            onSelect={(projectId) => void selectProject(projectId)}
            onNew={startNewProject}
          />
        </aside>

        <main className="stage-workspace">
          <section className="stage-panel">
            <div className="stage-panel-header">
              {activeStage === 3 ? (
                <div className="stage-tabs" role="tablist" aria-label="主图与文案子步骤">
                  <button className={stageThreeTab === "main" ? "is-active" : ""} type="button" role="tab" aria-selected={stageThreeTab === "main"} onClick={() => setStageThreeTab("main")}>
                    <Icon name="image" size={15} />主图处理
                    <span className={`tab-state ${mainImageConfirmed ? "is-done" : "is-pending"}`}>{mainImageConfirmed ? <Icon name="check" size={11} /> : null}</span>
                  </button>
                  <button className={stageThreeTab === "script" ? "is-active" : ""} type="button" role="tab" aria-selected={stageThreeTab === "script"} onClick={() => setStageThreeTab("script")}>
                    <Icon name="text" size={15} />口播文案
                    <span className={`tab-state ${scriptConfirmed ? "is-done" : "is-pending"}`}>{scriptConfirmed ? <Icon name="check" size={11} /> : null}</span>
                  </button>
                  <button className={stageThreeTab === "quality" ? "is-active" : ""} type="button" role="tab" aria-selected={stageThreeTab === "quality"} onClick={() => setStageThreeTab("quality")}>
                    <Icon name="quality" size={15} />内容质检
                    <span className={`tab-state ${contentQuality.report?.passed ? "is-done" : ""}`}>{contentQuality.report?.passed ? <Icon name="check" size={11} /> : null}</span>
                  </button>
                </div>
              ) : (
                <div className="workspace-section-title">
                  <span className="section-index">{String(activeStage).padStart(2, "0")}</span>
                  <strong>{activeStageDefinition.title}</strong>
                  <small>{activeStageDefinition.detail}</small>
                </div>
              )}
              <span className="workspace-stage-status">{formatWorkspaceStatus(pipeline?.status ?? null)}</span>
            </div>

            <div className="workspace-content-scroll">
              {activeStage === 1 ? (
                <div className="stage-stack">
                  {!project ? (
                    <section className="surface-card project-card">
                      <div className="section-heading">
                        <div><h2>商品信息</h2><p>创建项目后，所有素材和生成状态都会绑定到这个项目。</p></div>
                      </div>
                      <form onSubmit={handleCreateProject}>
                        <div className="form-grid">
                          <label className="field"><span>商品名称 <em>必填</em></span><input value={productName} onChange={(event) => setProductName(event.target.value)} placeholder="例如：便携式榨汁杯" maxLength={80} /></label>
                          <label className="field"><span>补充说明 <small>可选</small></span><textarea value={productNote} onChange={(event) => setProductNote(event.target.value)} placeholder="例如：白色杯身，包装上带有品牌文字" maxLength={240} rows={3} /></label>
                        </div>
                        {formError || error ? <div className="inline-error">{formError ?? error}</div> : null}
                        <div className="form-actions"><span>创建后会自动加入左侧项目列表。</span><button className="button button-primary" type="submit" disabled={isCreating}>{isCreating ? "正在创建…" : "创建项目"}</button></div>
                      </form>
                    </section>
                  ) : (
                    <>
                      <section className="surface-card project-card">
                        <div className="section-heading">
                          <div><h2>商品信息</h2><p>{isEditing ? "编辑后点击保存，项目列表会同步更新。" : "确认商品名称和补充说明。"}</p></div>
                          {isEditing ? (
                            <span className="inline-actions compact-actions"><button className="button button-secondary" type="button" onClick={cancelEditing} disabled={isSaving}>取消</button><button className="button button-primary" type="button" onClick={() => void saveProjectInfo()} disabled={isSaving}>{isSaving ? "保存中…" : "保存"}</button></span>
                          ) : <button className="button button-secondary" type="button" onClick={startEditing}>编辑</button>}
                        </div>
                        {isEditing ? (
                          <div className="project-edit-grid">
                            <label className="field compact-field"><span>商品名称 <em>必填</em></span><input value={draftProductName} onChange={(event) => setDraftProductName(event.target.value)} maxLength={80} /></label>
                            <label className="field compact-field"><span>补充说明 <small>可选</small></span><textarea value={draftProductNote} onChange={(event) => setDraftProductNote(event.target.value)} maxLength={240} rows={3} /></label>
                            {saveError ? <div className="inline-error">{saveError}</div> : null}
                          </div>
                        ) : (
                          <div className="project-info-grid">
                            <div className="project-info-item project-info-primary"><span>商品名称</span><strong>{project.product_name}</strong></div>
                            <div className="project-info-item"><span>补充说明</span><p>{project.product_note || "暂无"}</p></div>
                            <div className="project-id-row"><span>项目 ID</span><code>{project.project_id}</code><button className="copy-button" type="button" onClick={() => void copyProjectId()}>{copiedProjectId ? "已复制" : "复制"}</button></div>
                          </div>
                        )}
                      </section>

                      <section className="surface-card upload-section">
                        <div className="section-heading"><div><h2>商品图片</h2><p>支持 JPG、PNG、WebP，单图不超过 10 MB。</p></div><span className="count-chip">{uploads.validCount} / {MAX_ASSETS_PER_PROJECT}</span></div>
                        <UploadDropzone disabled={uploadDisabled} onFiles={(files) => void uploads.addFiles(files)} />
                        {uploads.notice ? <div className="inline-notice">{uploads.notice}</div> : null}
                        <div className="upload-actions"><div><strong>{uploads.readyCount} 张已完成</strong><span>{uploads.isBusy ? "正在处理图片…" : "失败文件可单独重试"}</span></div><button className="button button-primary" type="button" disabled={!uploads.hasQueued || uploads.isBusy} onClick={() => void uploads.startUploads()}>上传素材</button></div>
                        <div className="asset-list workspace-asset-list">
                          {uploads.isLoadingAssets ? <div className="empty-state compact"><span className="spinner" />读取素材中…</div> : uploads.items.length ? uploads.items.map((item) => <UploadAssetCard key={item.localId} item={item} onRetry={(localId) => void uploads.retryItem(localId)} />) : <div className="empty-state compact"><strong>还没有图片</strong><p>拖拽商品图到上方区域开始。</p></div>}
                        </div>
                      </section>
                    </>
                  )}
                </div>
              ) : null}

              {activeStage === 2 ? (
                <div className="stage-stack">
                  <RecognitionPanel state={recognition.recognition} readyAssetCount={uploads.readyCount} isStarting={recognition.isStarting} isConfirming={recognition.isConfirming} error={recognition.error} onStart={() => void recognition.start()} onConfirm={(assetId, candidateId) => void recognition.confirm(assetId, candidateId)} />
                </div>
              ) : null}

              {activeStage === 3 ? (
                <div className="stage-stack">
                  {stageThreeTab === "main" ? (
                    recognitionConfirmed || mainImage.state.version ? <MainImagePanel state={mainImage.state} canStart={recognitionConfirmed} isStarting={mainImage.isStarting} isConfirming={mainImage.isConfirming} error={mainImage.error} onStart={() => void mainImage.start()} onConfirm={() => void mainImage.confirm()} /> : <div className="stage-empty-state"><Icon name="lock" size={20} /><strong>主图阶段尚未解锁</strong><p>请先确认商品主体。</p></div>
                  ) : null}
                  {stageThreeTab === "script" ? (
                    mainImageConfirmed || script.state.version ? <ScriptPanel state={script.state} canStart={mainImageConfirmed} isStarting={script.isStarting} isSaving={script.isSaving} isConfirming={script.isConfirming} error={script.error} onStart={(input) => void script.start(input)} onSave={(input) => void script.save(input)} onConfirm={() => void script.confirm()} /> : <div className="stage-empty-state"><Icon name="lock" size={20} /><strong>文案阶段尚未解锁</strong><p>请先确认主图。</p></div>
                  ) : null}
                  {stageThreeTab === "quality" ? contentQuality.report ? <ContentQualityPanel report={contentQuality.report} isLoading={contentQuality.isLoading} error={contentQuality.error} /> : <div className="stage-empty-state"><Icon name="quality" size={20} /><strong>暂无质检结果</strong><p>完成视频方案后会生成内容质检报告。</p></div> : null}
                </div>
              ) : null}

              {activeStage === 4 ? (
                <div className="stage-stack">
                  {scriptConfirmed || voice.state.run ? <VoicePanel state={voice.state} canStart={scriptConfirmed} isStarting={voice.isStarting} error={voice.error} onStart={(input) => void voice.start(input)} /> : <div className="stage-empty-state"><Icon name="lock" size={20} /><strong>配音阶段尚未解锁</strong><p>请先确认口播文案。</p></div>}
                  {voiceReady || subtitle.state.version ? <SubtitlePanel state={subtitle.state} canStart={voiceReady} isSaving={subtitle.isSaving} isConfirming={subtitle.isConfirming} error={subtitle.error} onSave={(segments) => void subtitle.save(segments)} onConfirm={() => void subtitle.confirm()} /> : null}
                  {subtitleConfirmed || contentPlan.plan ? <ContentPlanPanel plan={contentPlan.plan} canStart={subtitleConfirmed} isGenerating={contentPlan.isGenerating} isSaving={contentPlan.isSaving} isConfirming={contentPlan.isConfirming} error={contentPlan.error} onGenerate={() => void contentPlan.generate()} onSave={(index, scenes) => void contentPlan.save(index, scenes)} onConfirm={() => void contentPlan.confirm()} /> : null}
                </div>
              ) : null}

              {activeStage === 5 ? (
                <div className="stage-stack">
                  {subtitleConfirmed || video.state.plan ? (
                    <VideoPanel state={video.state} output={video.output} canStart={subtitleConfirmed} voiceEnabled={voice.state.run?.enabled ?? true} subtitleEnabled={subtitle.state.version?.enabled ?? true} isStarting={video.isStarting} error={video.error} estimate={video.estimate} segments={video.segments} segmentBusy={video.segmentBusy} onGenerate={(mode, templateId) => void video.generate(mode, templateId)} onGenerateSegment={(segmentId) => void video.generateSegment(segmentId)} onAcceptSegment={(segmentId, candidateId) => void video.acceptSegment(segmentId, candidateId)} onRejectSegment={(segmentId) => void video.rejectSegment(segmentId)} onStartBatch={() => void video.startBatch()} onStopBatch={() => void video.stopBatch()} onConfirmEstimate={() => void video.confirmGenerate()} onCancelEstimate={video.cancelGenerate} />
                  ) : <div className="stage-empty-state"><Icon name="lock" size={20} /><strong>视频阶段尚未解锁</strong><p>请先确认配音与字幕。</p></div>}
                </div>
              ) : null}
            </div>
          </section>
        </main>

        <aside className="stage-inspector">
          <section className="inspector-block">
            <div className="inspector-block-heading"><span>阶段检查</span><strong>{inspectorItems.filter((item) => item.state === "done").length} / {inspectorItems.length}</strong></div>
            <ul className="stage-check-list">
              {inspectorItems.map((item) => (
                <li className={`is-${item.state}`} key={item.label}><span>{item.state === "done" ? <Icon name="check" size={13} /> : null}</span><div><strong>{item.label}</strong><small>{item.detail}</small></div></li>
              ))}
            </ul>
          </section>

          <section className="inspector-block">
            <div className="inspector-block-heading"><span>待处理</span><strong>{pendingItem.state === "done" ? "0" : "1"}</strong></div>
            {pendingItem.state === "done" ? <div className="pending-card is-complete"><Icon name="check" size={17} /><div><strong>当前阶段已完成</strong><small>可以进入下一阶段</small></div></div> : <div className="pending-card"><Icon name="alert" size={17} /><div><strong>{pendingItem.label}</strong><small>{pendingItem.detail}</small></div></div>}
          </section>

          <AgentDock project={project} />
        </aside>
      </div>
    </div>
  );
}


