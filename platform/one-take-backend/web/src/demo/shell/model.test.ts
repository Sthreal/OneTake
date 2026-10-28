import { describe, expect, it } from "vitest";

import {
  GS_STEPS,
  IMAGE_AD_CELLS,
  STUDIO_STEPS,
  gsDestinations,
  imageAdExportPayload,
  nextStudioView,
  normalizeStudioDraft,
  presenterOptions,
  resolveSelectedProduct,
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

  it("工作室草稿没有图片广告字段；指定了不存在的商品时不偷换", () => {
    const draft = normalizeStudioDraft({ ratio: "1:1", duration: "15s", presenterId: "premade:linxiao", projectId: null, points: ["texture"] });
    expect(draft).not.toHaveProperty("imageAd");
    expect(Object.keys(draft).sort()).toEqual(["duration", "points", "presenterId", "projectId", "ratio"]);
    const products = [{ project_id: "prj_a", product_name: "A" }];
    expect(resolveSelectedProduct("missing", products)).toBeNull();
    expect(resolveSelectedProduct(null, products)?.project_id).toBe("prj_a");
  });
});
