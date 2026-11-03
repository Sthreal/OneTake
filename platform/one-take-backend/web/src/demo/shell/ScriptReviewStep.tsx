/** 审稿步：三套角度可选，四维审完后 apply 或 ack，过闸才能确认并提交渲染。 */
import { useEffect, useState } from "react";

import type { Project } from "../../features/input/types";
import type { ScriptReviewResult, ScriptState, ScriptVersion } from "../../features/script/types";
import { ApiError } from "../../shared/api/client";
import {
  applyScriptReview,
  confirmScript,
  generateScript,
  getScript,
  reviewScriptGate,
  selectScript,
} from "../../shared/api/scriptApi";
import {
  reviewFeeHint,
  TALKING_HEAD_LIBRARY_PRESENTER_REQUIRED,
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
  explicitAngleRequired,
  gateHeadline,
  gateSummary,
  lengthFailureCopy,
  loadStudioScript,
  mergeReviewedVersion,
  orderedCandidates,
  paidVideoBlock,
  PREPARE_FACTS_CHANGED_HINT,
  regenerateStudioScript,
  reviewAngleGroupLabel,
  reviewFacts,
  prepareScriptInput,
  REVIEW_DIMENSIONS,
  ScriptPollingTimeoutError,
  scriptFailed,
  scriptFactChanges,
  scriptInFlight,
  scriptInputReady,
  scriptVersions,
} from "./scriptGate";
import { ensureShellMainImage } from "./mainImagePrelude";

const scriptClient = { getScript, generateScript };

export function ScriptReviewStep({
  product,
  presenter,
  draft,
  onAdvance,
  onBackToPrepare,
  pathHint = null,
  onDismissPathHint,
}: {
  product: Project | null;
  presenter: Pick<PresenterOption, "name" | "source">;
  draft: StudioDraft;
  onAdvance: () => void;
  onBackToPrepare: () => void;
  /** 路径改过且已有稿。不自动重出，只提示用户自己点重新生成。 */
  pathHint?: string | null;
  onDismissPathHint?: () => void;
}) {
  const [script, setScript] = useState<ScriptState | null>(null);
  const [review, setReview] = useState<ScriptReviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);

  const projectId = product?.project_id ?? null;

  useEffect(() => {
    if (!projectId || !product) {
      setScript(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setTimedOut(false);
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
        if (!cancelled) {
          if (err instanceof ScriptPollingTimeoutError) {
            setScript(err.state);
            setTimedOut(true);
          }
          setError(messageOf(err));
        }
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
  const name = product?.product_name ?? "已选商品";
  const angleGroup = reviewAngleGroupLabel({ source: presenter.source, path: draft.path });
  const presenterInvalid = draft.path === "talking_head" && presenter.source !== "library";
  const batchKey = angleBatchKey(script);
  const soft = angleConfirmSoftForce({
    path: draft.path,
    batchKey,
    pickedBatchKey: null,
    selectedStatus: version?.status,
    hasSelectableCandidate: candidates.some((item) => item.status === "ready"),
  });
  const currentInput = product ? prepareScriptInput(product, draft) : null;
  const factChanges = currentInput ? scriptFactChanges(version, currentInput) : [];

  async function choose(nextVersion: ScriptVersion) {
    if (!projectId || !script) return;
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

  async function confirmAndAdvance() {
    if (!projectId || !version) return;
    if (presenterInvalid) {
      setNotice("口播出镜必须先从当前出镜人库选择角色。请回准备步选择。");
      return;
    }
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
    setTimedOut(false);
    try {
      const next = await regenerateStudioScript(projectId, input, scriptClient, {
        ensureMainImage: ensureShellMainImage,
      });
      setScript(next);
      setReview(null);
      setNotice(null);
      setConflict(null);
      onDismissPathHint?.();
    } catch (err) {
      if (err instanceof ScriptPollingTimeoutError) {
        setScript(err.state);
        setTimedOut(true);
      }
      setError(messageOf(err));
    } finally {
      setBusy(null);
    }
  }

  async function continueWaiting() {
    if (!projectId || !product) return;
    const input = prepareScriptInput(product, draft);
    if (!scriptInputReady(input)) {
      setError("请先在准备步填写痛点、卖点和使用场景");
      return;
    }
    setBusy("wait");
    setError(null);
    try {
      const next = await loadStudioScript(projectId, input, scriptClient, {
        ensureMainImage: ensureShellMainImage,
      });
      setScript(next);
      setTimedOut(false);
      setNotice("已重新拿到口播状态。");
    } catch (err) {
      if (err instanceof ScriptPollingTimeoutError) {
        setScript(err.state);
        setTimedOut(true);
      }
      setError(messageOf(err));
    } finally {
      setBusy(null);
    }
  }

  const advanceDisabled = !version || guard.blocked || busy !== null || inFlight || version.status === "failed" || soft.blocked || presenterInvalid;

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
        <div className="ot-col">
            <section className="ot-panel" aria-busy={loading || busy !== null}>
              <div className="ot-label-row">
                <div className="ot-label">{angleGroup}</div>
                {locked ? <span className="ot-meta">已确认，再切会冲突</span> : null}
              </div>
              {explicitAngleRequired(draft.path) && candidates.length > 0 ? <p className="ot-hint">{ANGLE_PICK_GUIDE}</p> : null}
              {pathHint ? <p className="ot-hint" role="status">{pathHint}</p> : null}
              {factChanges.length > 0 ? (
                <div className="ot-banner" role="status">
                  <p>{PREPARE_FACTS_CHANGED_HINT}</p>
                  <p>变更字段：{factChanges.join("、")}</p>
                  <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" disabled={busy !== null} onClick={() => void retryGenerate()}>
                    按新事实重新生成
                  </button>
                </div>
              ) : null}
              {presenterInvalid ? (
                <div className="ot-banner" role="alert">
                  <p>{TALKING_HEAD_LIBRARY_PRESENTER_REQUIRED}。请回准备步选择。</p>
                  <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" onClick={onBackToPrepare}>回准备步选择出镜人</button>
                </div>
              ) : null}
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
              {timedOut ? (
                <div className="ot-cta-row" role="group" aria-label="口播生成超时恢复">
                  <button type="button" className="ot-btn ot-btn-primary ot-btn-sm" disabled={busy !== null} onClick={() => void continueWaiting()}>
                    {busy === "wait" ? "继续等待中…" : "继续等待"}
                  </button>
                  <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" disabled={busy !== null} onClick={() => void retryGenerate()}>
                    重新生成
                  </button>
                  <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" disabled={busy !== null} onClick={onBackToPrepare}>
                    回准备步
                  </button>
                </div>
              ) : null}
              {!timedOut && (failed || error || pathHint || factChanges.length > 0) ? (
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
                <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" disabled={!version || inFlight || timedOut || busy !== null || version.status === "failed"} onClick={() => void runReview()}>
                  {gate.status === "passed" || gate.status === "reviewed" || gate.status === "failed" ? "重新审稿" : "审稿"}
                </button>
                <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" disabled={!canApply || busy !== null} onClick={() => void decide("apply")}>应用改写</button>
                <button type="button" className="ot-btn ot-btn-secondary ot-btn-sm" disabled={!canAck || busy !== null} onClick={() => void decide("ack")}>保留原稿</button>
              </div>
            </section>
            <section className="ot-panel">
              <div className="ot-label">费用</div>
              <p className="ot-hint">本页不报价。确认后进入渲染，是否扣费以费用闸为准。</p>
              <div className="ot-hint">{reviewFeeHint(presenter)}</div>
            </section>
        </div>
      </div>
      <footer className="ot-sticky">
        <div>
          <div className="ot-sticky-title">{guard.blocked ? "提交渲染前要先过审稿闸" : "确认后提交渲染"}</div>
          <div className="ot-sticky-sub">
            {guard.blocked ? "未 apply / ack 时，付费视频会 409 SCRIPT_REVIEW_REQUIRED" : "下一步提交渲染，不是图片广告"}
          </div>
        </div>
        <div className="ot-sticky-right">
          <button type="button" className="ot-btn ot-btn-primary ot-btn-lg" disabled={advanceDisabled} onClick={() => void confirmAndAdvance()}>
            确认并提交渲染
          </button>
        </div>
      </footer>
    </>
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
