/** 壳层出稿前奏：文案接口要求主图 status=confirmed。
 *
 * 准备步的图只在浏览器里。这里在 generate 之前：
 * 已确认则直接返回；没有素材就把准备步那张图上传；再调
 * `POST /main-image/ensure`（识别 → 主图，Mock 下自动确认）。
 * 不跑自动链后半段，也不生成文案。
 */
import { inspectImageFile } from "../../features/input/validation";
import { completeAsset, listAssets, presignAsset } from "../../shared/api/assetApi";
import { apiRequest } from "../../shared/api/client";
import { prepareUploadFile } from "./model";

export const MAIN_IMAGE_REQUIRED_COPY = "请先确认主图，再生成文案";
export const MAIN_IMAGE_UPLOAD_COPY = "请先在准备步上传一张商品图。没有已确认主图时不能生成文案。";

export interface PreludeMainImage {
  status: string | null;
}

export interface MainImagePreludeClient {
  getMainImage(projectId: string): Promise<PreludeMainImage>;
  listReadyAssets(projectId: string): Promise<number>;
  uploadAsset(projectId: string, file: File): Promise<void>;
  ensureMainImage(projectId: string): Promise<PreludeMainImage>;
}

interface MainImagePayload {
  version: { status: string } | null;
}

function snapshot(payload: MainImagePayload | null | undefined): PreludeMainImage {
  return { status: payload?.version?.status ?? null };
}

export async function uploadPrepareAsset(projectId: string, file: File): Promise<void> {
  const metadata = await inspectImageFile(file);
  const presigned = await presignAsset(projectId, metadata);
  const put = await fetch(presigned.upload_url, {
    method: "PUT",
    headers: presigned.required_headers ?? {},
    body: file,
  });
  if (!put.ok) throw new Error(`图片上传失败（${put.status}）`);
  await completeAsset(projectId, presigned.asset_id, metadata);
}

export function getShellMainImage(projectId: string): Promise<MainImagePayload> {
  return apiRequest<MainImagePayload>(`/api/v1/projects/${projectId}/main-image`);
}

export function postEnsureMainImage(projectId: string): Promise<MainImagePayload> {
  return apiRequest<MainImagePayload>(`/api/v1/projects/${projectId}/main-image/ensure`, {
    method: "POST",
  });
}

export const shellMainImageClient: MainImagePreludeClient = {
  async getMainImage(projectId) {
    return snapshot(await getShellMainImage(projectId));
  },
  async listReadyAssets(projectId) {
    const assets = await listAssets(projectId);
    return assets.filter((item) => item.status === "ready").length;
  },
  uploadAsset: uploadPrepareAsset,
  async ensureMainImage(projectId) {
    return snapshot(await postEnsureMainImage(projectId));
  },
};

/** 已确认则什么都不做。否则补素材并确保主图 confirmed，再允许 generate。 */
export async function ensureMainImageBeforeScript(
  projectId: string,
  client: MainImagePreludeClient,
  file: File | null,
): Promise<void> {
  const current = await client.getMainImage(projectId);
  if (current.status === "confirmed") return;
  if ((await client.listReadyAssets(projectId)) < 1) {
    if (!file) throw new Error(MAIN_IMAGE_UPLOAD_COPY);
    await client.uploadAsset(projectId, file);
  }
  const next = await client.ensureMainImage(projectId);
  if (next.status !== "confirmed") throw new Error(MAIN_IMAGE_REQUIRED_COPY);
}

/** 审稿步出稿前调用。准备步上传的 File 还在内存里就用它补素材。 */
export function ensureShellMainImage(projectId: string): Promise<void> {
  return ensureMainImageBeforeScript(projectId, shellMainImageClient, prepareUploadFile(projectId));
}
