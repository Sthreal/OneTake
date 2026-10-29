import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  MAIN_IMAGE_REQUIRED_COPY,
  MAIN_IMAGE_UPLOAD_COPY,
  ensureMainImageBeforeScript,
  type MainImagePreludeClient,
} from "./mainImagePrelude";
import { emptySkuEnrichment, prepareUploadFile, resetPrepareMemory, writeSkuEnrichment } from "./model";

function client(partial: Partial<MainImagePreludeClient> & Pick<MainImagePreludeClient, "getMainImage">): MainImagePreludeClient {
  return {
    listReadyAssets: vi.fn(async () => 1),
    uploadAsset: vi.fn(async () => {}),
    ensureMainImage: vi.fn(async () => ({ status: "confirmed" })),
    ...partial,
  };
}

describe("壳层主图前奏", () => {
  beforeEach(() => {
    resetPrepareMemory();
  });

  it("主图已确认时不再上传、也不再 ensure", async () => {
    const api = client({
      getMainImage: vi.fn(async () => ({ status: "confirmed" })),
    });
    await ensureMainImageBeforeScript("prj", api, new File(["x"], "a.png", { type: "image/png" }));
    expect(api.listReadyAssets).not.toHaveBeenCalled();
    expect(api.uploadAsset).not.toHaveBeenCalled();
    expect(api.ensureMainImage).not.toHaveBeenCalled();
  });

  it("已有素材时直接 ensure，Mock 下要等到 confirmed", async () => {
    const api = client({
      getMainImage: vi.fn(async () => ({ status: "ready" })),
      listReadyAssets: vi.fn(async () => 1),
      ensureMainImage: vi.fn(async () => ({ status: "confirmed" })),
    });
    await ensureMainImageBeforeScript("prj", api, null);
    expect(api.uploadAsset).not.toHaveBeenCalled();
    expect(api.ensureMainImage).toHaveBeenCalledWith("prj");
  });

  it("没有素材就先上传准备步的图，再 ensure", async () => {
    const file = new File(["x"], "main.png", { type: "image/png" });
    const order: string[] = [];
    const api = client({
      getMainImage: async () => ({ status: null }),
      listReadyAssets: async () => 0,
      uploadAsset: async () => {
        order.push("upload");
      },
      ensureMainImage: async () => {
        order.push("ensure");
        return { status: "confirmed" };
      },
    });
    await ensureMainImageBeforeScript("prj", api, file);
    expect(order).toEqual(["upload", "ensure"]);
  });

  it("没有图也没有素材时，不会假装已经能确认主图", async () => {
    const api = client({
      getMainImage: async () => ({ status: null }),
      listReadyAssets: async () => 0,
    });
    await expect(ensureMainImageBeforeScript("prj", api, null)).rejects.toThrow(MAIN_IMAGE_UPLOAD_COPY);
    expect(api.ensureMainImage).not.toHaveBeenCalled();
  });

  it("ensure 没把主图确认下来时，仍抛出原来的闸门文案", async () => {
    const api = client({
      getMainImage: async () => ({ status: "ready" }),
      ensureMainImage: async () => ({ status: "ready" }),
    });
    await expect(ensureMainImageBeforeScript("prj", api, null)).rejects.toThrow(MAIN_IMAGE_REQUIRED_COPY);
  });

  it("准备步留下的 File 还能被前奏读到", () => {
    const file = new File(["png"], "cup.png", { type: "image/png" });
    writeSkuEnrichment("prj_file", {
      ...emptySkuEnrichment(),
      images: [{ id: "1", name: "cup.png", mime: "image/png", size: 3, preview: "blob:cup", file }],
    });
    expect(prepareUploadFile("prj_file")).toBe(file);
    expect(prepareUploadFile("prj_other")).toBeNull();
  });
});
