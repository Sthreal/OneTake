import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { completeAsset, listAssets, presignAsset } from "../../shared/api/assetApi";
import type { ImageMetadata, ServerAsset } from "./types";
import { useAssetUploads } from "./useAssetUploads";
import { inspectImageFile } from "./validation";

vi.mock("../../shared/api/assetApi", () => ({
  listAssets: vi.fn(),
  presignAsset: vi.fn(),
  completeAsset: vi.fn(),
}));

vi.mock("./validation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./validation")>();
  return { ...actual, inspectImageFile: vi.fn() };
});

const mockedListAssets = vi.mocked(listAssets);
const mockedPresign = vi.mocked(presignAsset);
const mockedComplete = vi.mocked(completeAsset);
const mockedInspect = vi.mocked(inspectImageFile);

const SHA256 = "a".repeat(64);
const PROJECT_ID = "prj_upload_retry";

const METADATA: ImageMetadata = {
  originalFilename: "product.png",
  mimeType: "image/png",
  sizeBytes: 2048,
  width: 600,
  height: 600,
  sha256: SHA256,
};

type ProgressHandler = (event: ProgressEvent) => void;

class FakeXhr {
  static putFails = false;

  status = 0;
  upload: { onprogress: ProgressHandler | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  open(): void {}

  setRequestHeader(): void {}

  send(): void {
    if (FakeXhr.putFails) {
      // 模拟 PUT 到对象存储时的网络失败
      this.onerror?.();
      return;
    }
    this.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 2 } as ProgressEvent);
    this.status = 200;
    this.onload?.();
  }
}

function makeFile(): File {
  return new File([new Uint8Array([1, 2, 3])], "product.png", { type: "image/png" });
}

function presignedUpload(assetId: string) {
  return {
    asset_id: assetId,
    object_key: `projects/${PROJECT_ID}/assets/${assetId}/original.png`,
    upload_url: `https://minio.test/onetake-media/projects/${PROJECT_ID}/assets/${assetId}/original.png`,
    expires_at: "2026-10-12T00:15:00Z",
    required_headers: { "Content-Type": "image/png" },
  };
}

function readyAsset(assetId: string): ServerAsset {
  return {
    asset_id: assetId,
    project_id: PROJECT_ID,
    object_key: `projects/${PROJECT_ID}/assets/${assetId}/original.png`,
    original_filename: "product.png",
    mime_type: "image/png",
    size_bytes: 2048,
    width: 600,
    height: 600,
    sha256: SHA256,
    status: "ready",
    created_at: "2026-10-12T00:00:00Z",
    updated_at: "2026-10-12T00:00:00Z",
    completed_at: "2026-10-12T00:00:00Z",
  };
}

async function renderUploads() {
  const hook = renderHook(() => useAssetUploads(PROJECT_ID));
  // 等首次素材列表加载落地：它的 replaceItems 会覆盖随后添加的本地文件
  await waitFor(() => expect(mockedListAssets).toHaveBeenCalled());
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  await act(async () => {
    await hook.result.current.addFiles([makeFile()]);
  });
  await act(async () => {
    await hook.result.current.startUploads();
  });
  return hook;
}

describe("useAssetUploads retry", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    FakeXhr.putFails = false;
    mockedListAssets.mockResolvedValue([]);
    mockedInspect.mockResolvedValue(METADATA);
    // 服务端对同一 sha256 的 pending 素材是幂等的：重复预签名返回同一个 assetId
    mockedPresign.mockResolvedValue(presignedUpload("ast_pending"));
    mockedComplete.mockResolvedValue(readyAsset("ast_pending"));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("marks a failed PUT as the upload stage instead of the presign stage", async () => {
    FakeXhr.putFails = true;

    const { result } = await renderUploads();

    await waitFor(() => expect(result.current.items[0].status).toBe("failed"));
    // 回归点：预签名成功后 assetId 已写回 state，快照读到空值会把这里误判成 presign
    expect(result.current.items[0].errorStage).toBe("upload");
    expect(result.current.items[0].assetId).toBe("ast_pending");
  });

  it("marks a failed presign as the presign stage", async () => {
    mockedPresign.mockRejectedValue(new Error("网络错误，预签名失败"));

    const { result } = await renderUploads();

    await waitFor(() => expect(result.current.items[0].status).toBe("failed"));
    expect(result.current.items[0].errorStage).toBe("presign");
    expect(result.current.items[0].assetId).toBeUndefined();
  });

  it("reuses the same pending asset when retrying after a failed PUT", async () => {
    FakeXhr.putFails = true;

    const { result } = await renderUploads();
    await waitFor(() => expect(result.current.items[0].status).toBe("failed"));
    const localId = result.current.items[0].localId;

    FakeXhr.putFails = false;
    await act(async () => {
      await result.current.retryItem(localId);
    });

    await waitFor(() => expect(result.current.items[0].status).toBe("ready"));
    expect(result.current.items[0].errorStage).toBeUndefined();
    expect(result.current.items[0].error).toBeUndefined();
    // 重试重新预签名，但服务端返回的是同一个 assetId，complete 也只提交这一个素材
    expect(mockedPresign).toHaveBeenCalledTimes(2);
    expect(mockedComplete).toHaveBeenCalledTimes(1);
    expect(mockedComplete.mock.calls[0][1]).toBe("ast_pending");
  });

  it("retries only the complete step when the upload already succeeded", async () => {
    mockedComplete.mockRejectedValueOnce(new Error("复核失败"));

    const { result } = await renderUploads();
    await waitFor(() => expect(result.current.items[0].status).toBe("failed"));
    expect(result.current.items[0].errorStage).toBe("complete");
    const localId = result.current.items[0].localId;

    await act(async () => {
      await result.current.retryItem(localId);
    });

    await waitFor(() => expect(result.current.items[0].status).toBe("ready"));
    // 已经上传成功，重试不应再次预签名，也就不会多占一个素材配额
    expect(mockedPresign).toHaveBeenCalledTimes(1);
    expect(mockedComplete).toHaveBeenCalledTimes(2);
  });
});