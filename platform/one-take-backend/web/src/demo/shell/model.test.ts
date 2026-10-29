import { describe, expect, it } from "vitest";

import {
  DEFAULT_STUDIO_DRAFT,
  GS_STEPS,
  IMAGE_AD_CELLS,
  PREPARE_IMAGE_MAX_BYTES,
  PREPARE_REQUIRED_COPY,
  STUDIO_STEPS,
  applyPrepareEdit,
  effectivePrepareFields,
  emptySkuEnrichment,
  gsDestinations,
  imageAdExportPayload,
  nextStudioView,
  normalizeStudioDraft,
  prepareImageRejection,
  prepareSubmitErrors,
  presenterOptions,
  readSkuEnrichment,
  readStudioDraft,
  resolveSelectedProduct,
  writeSkuEnrichment,
} from "./model";

describe("iter18 信息架构", () => {
  it("上手四步目的地互不相同，第二步是图片广告", () => {
    expect(GS_STEPS.map((step) => step.name)).toEqual(["加商品", "图片广告", "生成视频", "发布广告"]);
    expect(gsDestinations()).toEqual(["brand", "image", "prepare", "connect"]);
    expect(new Set(gsDestinations()).size).toBe(4);
    expect(GS_STEPS[1].cta).toBe("去图片广告");
    expect(GS_STEPS[3].optional).toBe(true);
  });

  it("工作室只有准备 → 审稿 → 生成 → 成片，下一步不会进图片广告", () => {
    expect(STUDIO_STEPS.map((step) => step.view)).toEqual(["prepare", "review", "generate", "delivery"]);
    expect(nextStudioView("prepare")).toBe("review");
    expect(nextStudioView("review")).toBe("generate");
    expect(nextStudioView("generate")).toBe("delivery");
    expect(nextStudioView("delivery")).toBeNull();
    expect(nextStudioView("image")).toBeNull();
    expect(nextStudioView("brand")).toBeNull();
  });

  it("图片广告是 3×3 九宫格，导出文案不把静图当成视频前置", () => {
    expect(IMAGE_AD_CELLS).toHaveLength(9);
    const payload = imageAdExportPayload({ caption: "白底棚拍", ratio: "1:1", productName: "春季护肤精华液" });
    expect(payload.filename).toContain("白底棚拍");
    expect(payload.text).toContain("这不是真实图片");
    expect(payload.text).toContain("不把图片广告当作前置步骤");
  });

  it("出镜人只有预制和库，准备步不能从提示词现造一个", () => {
    const options = presenterOptions([
      { character_id: "chr_1", name: "周予", voice_style: "男声 · 库" },
    ]);
    expect(options.map((item) => item.source)).toEqual(["premade", "library"]);
    expect(options[0].name).toBe("林晓");
    expect(options.some((item) => item.id.startsWith("prompt"))).toBe(false);
  });

  it("工作室草稿没有图片广告字段；没有 id 或 id 不存在时都不偷换", () => {
    const draft = normalizeStudioDraft({
      ratio: "1:1",
      duration: "15s",
      presenterId: "premade:linxiao",
      projectId: null,
      points: ["texture", "promo"],
    });
    expect(draft).not.toHaveProperty("imageAd");
    expect(draft).not.toHaveProperty("points");
    expect(draft.selling_points).toBeNull();
    expect(Object.keys(draft).sort()).toEqual([
      "duration",
      "offer",
      "pain_point",
      "presenterId",
      "projectId",
      "ratio",
      "selling_points",
      "sessionOnly",
      "specs",
      "usage_scenario",
    ]);
    const products = [
      { project_id: "prj_a", product_name: "A" },
      { project_id: "prj_b", product_name: "B" },
    ];
    expect(resolveSelectedProduct("missing", products)).toBeNull();
    expect(resolveSelectedProduct(null, products)).toBeNull();
    expect(resolveSelectedProduct("prj_b", products)?.product_name).toBe("B");
  });
});

describe("准备步草稿与商品富化", () => {
  it("把 v1 草稿迁到 v2，并丢掉旧的卖点 checkbox id", () => {
    localStorage.setItem("onetake.studioDraft.v1", JSON.stringify({
      projectId: "prj_a",
      presenterId: "premade:linxiao",
      ratio: "1:1",
      duration: "15s",
      points: ["texture", "promo"],
    }));
    const draft = readStudioDraft(null);
    expect(draft.projectId).toBe("prj_a");
    expect(draft.ratio).toBe("1:1");
    expect(draft.selling_points).toBeNull();
    expect(draft.pain_point).toBeNull();
    expect(draft).not.toHaveProperty("points");
    expect(localStorage.getItem("onetake.studioDraft.v1")).toBeNull();
    const stored = JSON.parse(localStorage.getItem("onetake.studioDraft.v2") ?? "{}") as { points?: unknown };
    expect(stored.points).toBeUndefined();
  });

  it("两件商品各自记卖点；仅本次出片不写回另一件", () => {
    const base = emptySkuEnrichment();
    writeSkuEnrichment("prj_a", { ...base, pain_point: "甲的痛点", selling_points: ["甲卖点"], usage_scenario: "甲的场景" });
    writeSkuEnrichment("prj_b", { ...base, pain_point: "乙的痛点", selling_points: ["乙卖点"], usage_scenario: "乙的场景" });
    const draft = { ...DEFAULT_STUDIO_DRAFT, projectId: "prj_a" };
    expect(effectivePrepareFields("prj_a", draft).selling_points).toEqual(["甲卖点"]);
    expect(effectivePrepareFields("prj_b", draft).selling_points).toEqual(["乙卖点"]);

    const session = applyPrepareEdit("prj_a", { ...draft, sessionOnly: true }, {
      ...base,
      pain_point: "只在这一次",
      selling_points: ["临时卖点"],
      usage_scenario: "临时场景",
    });
    expect(session.sessionOnly).toBe(true);
    expect(session.pain_point).toBe("只在这一次");
    expect(readSkuEnrichment("prj_a").pain_point).toBe("甲的痛点");
    expect(readSkuEnrichment("prj_b").selling_points).toEqual(["乙卖点"]);
    expect(effectivePrepareFields("prj_a", session).pain_point).toBe("只在这一次");
    expect(effectivePrepareFields("prj_b", session).pain_point).toBe("乙的痛点");
    expect(effectivePrepareFields("prj_b", session).selling_points).toEqual(["乙卖点"]);
  });

  it("图片只收 PNG / JPEG / JPG / WEBP，且不超过 10MB；必填文案按准备步拦截", () => {
    expect(prepareImageRejection({ name: "a.heic", type: "image/heic", size: 100 })).toBe("仅支持 PNG / JPEG / JPG / WEBP");
    expect(prepareImageRejection({ name: "a.gif", type: "image/gif", size: 100 })).toBe("仅支持 PNG / JPEG / JPG / WEBP");
    expect(prepareImageRejection({ name: "a.png", type: "image/png", size: PREPARE_IMAGE_MAX_BYTES + 1 })).toBe("单张不能超过 10MB");
    expect(prepareImageRejection({ name: "a.jpg", type: "image/jpeg", size: PREPARE_IMAGE_MAX_BYTES })).toBeNull();
    expect(prepareImageRejection({ name: "a.jpeg", type: "image/jpeg", size: 32 })).toBeNull();
    expect(prepareImageRejection({ name: "a.webp", type: "image/webp", size: 32 })).toBeNull();
    expect(prepareImageRejection({ name: "a.PNG", type: "", size: 32 })).toBeNull();
    expect(prepareSubmitErrors({ imageCount: 0, painPoint: "", sellingPoints: ["  "], usageScenario: "通勤" })).toEqual([
      PREPARE_REQUIRED_COPY.image,
      PREPARE_REQUIRED_COPY.pain,
      PREPARE_REQUIRED_COPY.points,
    ]);
    expect(prepareSubmitErrors({ imageCount: 1, painPoint: "清洗麻烦", sellingPoints: ["杯身可拆"], usageScenario: "" })).toEqual([
      PREPARE_REQUIRED_COPY.scene,
    ]);
  });
});
