/** 审稿步：三套角度可选，四维审完后 apply 或 ack，过闸才能确认并进入生成。 */
import { useEffect, useState } from "react";

import type { Project } from "../../features/input/types";
import type { EditScriptInput, ScriptReviewResult, ScriptState, ScriptVersion } from "../../features/script/types";
import { ApiError } from "../../shared/api/client";
import {
  applyScriptReview,
  confirmScript,
  editScript,
  generateScript,
  getScript,
  reviewScriptGate,
  selectScript,
} from "../../shared/api/scriptApi";
import {
  DEMO_FEE,
  REVIEW_FILTERS,
  reviewFeeHint,
  visibleReviewCells,
  type PresenterOption,
  type StudioDraft,
} from "./model";
import {
  ackAllowed,
  ANGLE_PICK_GUIDE,
  ANGLE_PICK_HINT,
  angleBatchKey,
  angleConfirmSoftForce,
  angleLabel,
  angleSwitchLocked,
  applyAllowed,
  editResetGate,
  gateHeadline,
  gateSummary,
  lengthFailureCopy,
  loadStudioScript,
  mergeReviewedVersion,
  orderedCandidates,
  paidVideoBlock,
  regenerateStudioScript,
  reviewAngleGroupLabel,
  reviewFacts,
  REVIEW_DIMENSIONS,
  sameEdit,
  prepareScriptInput,
  scriptFailed,
  scriptInFlight,
  scriptInputReady,
  scriptVersions,
  toEditInput,
} from "./scriptGate";
import { ensureShellMainImage } from "./mainImagePrelude";

const scriptClient = { getScript, generateScript };

export function ScriptReviewStep({
  product,
  presenter,
  draft,
  onAdvance,
  pathHint = null,
  onDismissPathHint,
}: {
  product: Project | null;
  presenter: Pick<PresenterOption, "name" | "source">;
  draft: StudioDraft;
  onAdvance: () => void;
  /** 路径改过且已有稿。不自动重出，只提示用户自己点重新生成。 */
  pathHint?: string | null;
  onDismissPathHint?: () => void;
}) {
  const [filter, setFilter] = useState<(typeof REVIEW_FILTERS)[number]>("全部");
  const [script, setScript] = useState<ScriptState | null>(null);
  const [review, setReview] = useState<ScriptReviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  /** 用户在这一批里点过角卡片。默认高亮不算。换 project 或重新生成会清掉。 */
  const [pickedBatchKey, setPickedBatchKey] = useState<string | null>(null);

  const projectId = product?.project_id ?? null;

  useEffect(() => {
    setPickedBatchKey(null);
  }, [projectId]);

  useEffect(() => {
    if (!projectId || !product) {
      setScript(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const existing = await getScript(projectId);
        if (cancelled) return;
        const input = prepareScriptInput(product, draft);
        if (scriptVersions(existing).length === 0 && !scriptInputReady(input)) {
          setScript(null);
          setError("请先在准备步填写痛点、卖点和使用场景");
          return;
        }
        const next = await loadStudioScript(projectId, input, scriptClient, {
          ensureMainImage: ensureShellMainImage,
        });
        if (!cancelled) setScript(next);
      } catch (err) {
        if (!cancelled) setError(messageOf(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // 卖点只在首次出稿时读取。已有 ready 稿再改准备步，不会悄悄另开一批。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const version = script?.version ?? null;
  const candidates = orderedCandidates(script);
  const facts = reviewFacts(review, version);
  const gate = gateSummary(version);
  const guard = paidVideoBlock(version);
  const canApply = applyAllowed(facts);
  const canAck = ackAllowed(facts);
  const lengthCopy = lengthFailureCopy(facts);
  const locked = angleSwitchLocked(script);
  const inFlight = scriptInFlight(script);
  const failed = scriptFailed(script);
  const cells = visibleReviewCells(filter);
  const name = product?.product_name ?? "已选商品";
  const angleGroup = reviewAngleGroupLabel({ source: presenter.source, path: draft.path });
  const batchKey = angleBatchKey(script);
  const soft = angleConfirmSoftForce({
    path: draft.path,
    batchKey,
    pickedBatchKey,
    selectedStatus: version?.status,
    hasSelectableCandidate: candidates.some((item) => item.status === "ready"),
  });

  function markAnglePicked() {
    if (batchKey) setPickedBatchKey(batchKey);
  }

  async function choose(nextVersion: ScriptVersion) {
    if (!projectId || !script) return;
    markAnglePicked();
    if (nextVersion.version_id === script.selected_version_id) return;
    setBusy("select");
    setConflict(null);
    try {
      const next = await selectScript(projectId, nextVersion.version_id);
      setScript(next);
      setReview(null);
      setNotice(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setConflict(err.message || "文案已确认，不能再切换角度");
      } else {
        setConflict(messageOf(err));
      }
    } finally {
      setBusy(null);
    }
  }

  async function runReview() {
    if (!projectId) return;
    setBusy("review");
    setError(null);
    setNotice(null);
    try {
      const result = await reviewScriptGate(projectId);
      setReview(result);
      setScript((current) => (current ? mergeReviewedVersion(current, result.version) : { version: result.version, candidates: [result.version], selected_version_id: result.version.version_id }));
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(null);
    }
  }

  async function decide(action: "apply" | "ack") {
    if (!projectId) return;
    setBusy(action);
    setError(null);
    try {
      const result = await applyScriptReview(projectId, action);
      setReview(result);
      setScript((current) => (current ? mergeReviewedVersion(current, result.version) : { version: result.version, candidates: [result.version], selected_version_id: result.version.version_id }));
      setNotice(action === "apply" ? "已写入改写，审稿闸通过。" : "已保留原稿，审稿闸通过。");
    } catch (err) {
      if (err instanceof ApiError && (err.code === "SCRIPT_REVIEW_LENGTH" || err.status === 409)) {
        setNotice(err.message || "这次改写不能应用，请保留原稿");
      } else {
        setError(messageOf(err));
      }
    } finally {
      setBusy(null);
    }
  }

  async function saveEdit(input: EditScriptInput) {
    if (!projectId || !version) return;
    const before = gateSummary(version);
    setBusy("edit");
    setError(null);
    try {
      const next = await editScript(projectId, input);
      setScript(next);
      setReview(null);
      if (editResetGate(before, gateSummary(next.version))) {
        setNotice("手改文案已清掉审稿闸，需要重新审稿。");
      } else {
        setNotice("文案已保存。");
      }
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(null);
    }
  }

  async function confirmAndAdvance() {
    if (!projectId || !version) return;
    if (soft.blocked) {
      setNotice(ANGLE_PICK_HINT);
      return;
    }
    const block = paidVideoBlock(version);
    if (block.blocked) {
      setNotice(block.message);
      return;
    }
    if (version.status === "confirmed") {
      onAdvance();
      return;
    }
    setBusy("confirm");
    setError(null);
    try {
      const next = await confirmScript(projectId);
      setScript(next);
      onAdvance();
    } catch (err) {
      if (err instanceof ApiError && err.code === "SCRIPT_REVIEW_REQUIRED") {
        setNotice(err.message || "确认前要先过审稿闸");
      } else {
        setError(messageOf(err));
      }
    } finally {
      setBusy(null);
    }
  }

  async function retryGenerate() {
    if (!projectId || !product) return;
    const input = prepareScriptInput(product, draft);
    if (!scriptInputReady(input)) {
      setError("请先在准备步填写痛点、卖点和使用场景");
      return;
    }
    setBusy("generate");
    setError(null);
    try {
      const next = await regenerateStudioScript(projectId, input, scriptClient, {
        ensureMainImage: ensureShellMainImage,
      });
      setPickedBatchKey(null);
      setScript(next);
      setReview(null);
      setNotice(null);
      setConflict(null);
      onDismissPathHint?.();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(null);
    }
  }

  const advanceDisabled = !version || guard.blocked || busy !== null || inFlight || version.status === "failed" || soft.blocked;

  return (
    <>
      <div className="ot-content">
        <div className="ot-headrow">
          <div>
            <h1 className="ot-page-title">审稿确认</h1>
            <p className="ot-page-sub">选出一套{angleGroup}并过审稿闸，确认后才提交渲染。无需先做图片广告。</p>
          </div>
          <div className="ot-context">商品 <strong>{name}</strong></div>
        </div>
        <div className="ot-split">
          <div className="ot-col">
            <section className="ot-preview">
              <div className="ot-preview-bar">
                <div className="ot-ptabs">
                  <button type="button">分镜预览</button>
                  <button type="button">关键帧</button>
                  <button type="button" className="on">九宫格</button>
                </div>
                <div className="ot-meta">{draft.duration} · {draft.ratio} · 9 镜</div>
              </div>
              <div className="ot-preview-body">
                <div className="ot-filters-inline" role="group" aria-label="分镜筛选">
                  {REVIEW_FILTERS.map((item) => (
                    <button key={item} type="button" className={item === filter ? "on" : ""} aria-pressed={item === filter} onClick={() => setFilter(item)}>{item}</button>
                  ))}
                </div>
                <div className="ot-nine" role="list" aria-label="审稿九宫格">
                  {cells.map((cell) => (
                    <div key={cell.id} role="listitem" className="ot-cell" style={{ minHeight: 96 }}>
                      <span className={"ot-cell-bg " + cell.tone} />
                      <span className="ot-cell-tag">镜 {cell.id}<span className="dur">{cell.dur}</span></span>
                      <span className="ot-cell-cap">{cell.caption}</span>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          </div>
          <div className="ot-side-col">
            <section className="ot-panel" aria-busy={loading || busy !== null}>
              <div className="ot-label-row">
                <div className="ot-label">{angleGroup}</div>
                {locked ? <span className="ot-meta">已确认，再切会冲突</span> : null}
              </div>
              {soft.blocked ? <p className="ot-hint">{ANGLE_PICK_GUIDE}</p> : null}
              {pathHint ? <p className="ot-hint" role="status">{pathHint}</p> : null}
              {!product ? <p className="ot-hint">先在准备步选用商品，才能生成三套口播。</p> : null}
              {loading ? <p className="ot-hint">正在确认主图并准备三套口播…</p> : null}
              {error ? <p className="ot-error">{error}</p> : null}
              {conflict ? <p className="ot-error" role="alert">{conflict}</p> : null}
              {candidates.length > 0 ? (
                <div className="ot-angles" role="group" aria-label={angleGroup}>
                  {candidates.map((item) => {
                    const selected = item.version_id === (script?.selected_version_id ?? version?.version_id);
                    const label = angleLabel(item);
                    return (
                      <button
                        key={item.version_id}
                        type="button"
                        className={"ot-angle" + (selected ? " on" : "")}
                        aria-pressed={selected}
                        aria-label={label}
                        disabled={busy === "select" || item.status === "queued" || item.status === "generating"}
                        onClick={() => void choose(item)}
                      >
                        <span className="ot-angle-name">{label}</span>
                        <span className="ot-angle-hook">
                          {item.status === "queued" || item.status === "generating"
                            ? "生成中"
                            : item.status === "failed"
                              ? "生成失败"
                              : item.hook || "暂无钩子"}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : null}
              {failed || error || pathHint ? (
                <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" disabled={busy !== null} onClick={() => void retryGenerate()}>重新生成三套口播</button>
              ) : null}
            </section>
            <section className="ot-panel">
              <div className="ot-label">审稿闸</div>
              <p className="ot-gate" role="status">{version ? gateHeadline(gate) : "审稿闸：未开始"}</p>
              {notice ? <p className="ot-banner" role="status">{notice}</p> : null}
              {lengthCopy ? <p className="ot-banner">{lengthCopy}</p> : null}
              <div className="ot-dims" role="list" aria-label="四维审稿">
                {REVIEW_DIMENSIONS.map((dim) => {
                  const item = review?.dimensions?.[dim.id];
                  return (
                    <div key={dim.id} role="listitem" className="ot-dim">
                      <span>{dim.label}</span>
                      <b>{item ? (item.passed ? "通过" : "未通过") : "—"}</b>
                    </div>
                  );
                })}
              </div>
              {review?.revised && review.changed_fields.length > 0 ? (
                <p className="ot-hint">改写字段：{review.changed_fields.join("、")}。应用后才会写入当前稿。</p>
              ) : null}
              {review?.revised ? <div className="ot-script">{review.revised.hook}</div> : null}
              <div className="ot-cta-row">
                <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" disabled={!version || inFlight || busy !== null || version.status === "failed"} onClick={() => void runReview()}>
                  {gate.status === "passed" || gate.status === "reviewed" || gate.status === "failed" ? "重新审稿" : "审稿"}
                </button>
                <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" disabled={!canApply || busy !== null} onClick={() => void decide("apply")}>应用改写</button>
                <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" disabled={!canAck || busy !== null} onClick={() => void decide("ack")}>保留原稿</button>
              </div>
            </section>
            {version && !inFlight && version.status !== "failed" ? (
              <section className="ot-panel">
                <div className="ot-label">手改口播</div>
                <CopyEditor version={version} disabled={busy !== null} onSave={saveEdit} />
              </section>
            ) : null}
            <section className="ot-panel">
              <div className="ot-label">费用明细</div>
              <div className="ot-fee-row"><span>文案与分镜</span><b>已含</b></div>
              <div className="ot-fee-row"><span>配音合成</span><b>2 积分</b></div>
              <div className="ot-fee-row"><span>视频生成 · {draft.duration}</span><b>10 积分</b></div>
              <div className="ot-divider" />
              <div className="ot-fee-row"><span>合计</span><span className="ot-fee-total">{DEMO_FEE} 积分</span></div>
              <div className="ot-hint">{reviewFeeHint(presenter)}</div>
            </section>
          </div>
        </div>
      </div>
      <footer className="ot-sticky">
        <div>
          <div className="ot-sticky-title">{guard.blocked ? "生成前要先过审稿闸" : "确认后提交渲染"}</div>
          <div className="ot-sticky-sub">
            {guard.blocked ? "未 apply / ack 时，付费视频会 409 SCRIPT_REVIEW_REQUIRED" : "下一步提交渲染，不是图片广告"}
          </div>
        </div>
        <div className="ot-sticky-right">
          {soft.hint ? <span className="ot-meta" role="status">{soft.hint}</span> : null}
          <button type="button" className="ot-btn ot-btn-primary ot-btn-lg" disabled={advanceDisabled} onClick={() => void confirmAndAdvance()}>
            确认并生成成片<span className="ot-fee">· {DEMO_FEE} 积分</span>
          </button>
        </div>
      </footer>
    </>
  );
}

function CopyEditor({
  version,
  disabled,
  onSave,
}: {
  version: ScriptVersion;
  disabled: boolean;
  onSave: (input: EditScriptInput) => Promise<void>;
}) {
  const [form, setForm] = useState<EditScriptInput>(() => toEditInput(version));
  useEffect(() => {
    setForm(toEditInput(version));
  }, [version]);
  const dirty = !sameEdit(form, version);
  const pointsText = form.sellingPoints.join("\n");
  return (
    <form
      className="ot-fields"
      onSubmit={(event) => {
        event.preventDefault();
        if (!dirty || disabled) return;
        const sellingPoints = pointsText.split("\n").map((item) => item.trim()).filter(Boolean).slice(0, 5);
        if (sellingPoints.length === 0) return;
        void onSave({ ...form, sellingPoints });
      }}
    >
      <label>
        钩子
        <input value={form.hook} disabled={disabled} onChange={(event) => setForm({ ...form, hook: event.target.value })} />
      </label>
      <label>
        痛点
        <input value={form.painPoint} disabled={disabled} onChange={(event) => setForm({ ...form, painPoint: event.target.value })} />
      </label>
      <label>
        卖点
        <textarea rows={2} value={pointsText} disabled={disabled} onChange={(event) => setForm({ ...form, sellingPoints: event.target.value.split("\n") })} />
      </label>
      <label>
        场景
        <input value={form.usageScenario} disabled={disabled} onChange={(event) => setForm({ ...form, usageScenario: event.target.value })} />
      </label>
      <label>
        行动号召
        <input value={form.cta} disabled={disabled} onChange={(event) => setForm({ ...form, cta: event.target.value })} />
      </label>
      <button type="submit" className="ot-btn ot-btn-secondary ot-btn-sm" disabled={disabled || !dirty}>保存手改</button>
      <p className="ot-hint">手改会清掉审稿闸，保存后要重新审稿。</p>
    </form>
  );
}

export function useScriptGateGuard(projectId: string | null) {
  const [guard, setGuard] = useState<{ loading: boolean; blocked: boolean; message: string }>({
    loading: Boolean(projectId),
    blocked: true,
    message: projectId ? "正在核对审稿闸…" : paidVideoBlock(null).message,
  });

  useEffect(() => {
    if (!projectId) {
      setGuard({ loading: false, blocked: true, message: paidVideoBlock(null).message });
      return;
    }
    let cancelled = false;
    setGuard((current) => ({ ...current, loading: true, blocked: true, message: "正在核对审稿闸…" }));
    void getScript(projectId)
      .then((state) => {
        if (cancelled) return;
        const block = paidVideoBlock(state.version);
        setGuard({
          loading: false,
          blocked: block.blocked,
          message: block.blocked ? block.message : "审稿闸已通过，可以进入成片。",
        });
      })
      .catch(() => {
        if (cancelled) return;
        setGuard({
          loading: false,
          blocked: true,
          message: "核对审稿闸失败。请回审稿步完成 apply 或 ack。未完成时付费视频会返回 409 SCRIPT_REVIEW_REQUIRED。",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return guard;
}

function messageOf(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "请求失败";
}
