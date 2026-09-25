import type { ImageMetadata } from "./types";

export const ACCEPTED_MIME_TYPES = ["image/jpeg", "image/png", "image/webp"] as const;
export const MAX_ASSETS_PER_PROJECT = 5;
export const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;
export const MIN_SHORT_SIDE = 512;
export const MAX_LONG_SIDE = 6000;
export const MAX_PIXELS = 24_000_000;
export const MAX_ASPECT_RATIO = 5;

export class ImageValidationError extends Error {}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function validateFileBasics(file: File): string | null {
  if (!ACCEPTED_MIME_TYPES.includes(file.type as (typeof ACCEPTED_MIME_TYPES)[number])) {
    return "仅支持 JPG、PNG 和 WebP";
  }
  if (file.size <= 0) return "图片大小必须大于 0";
  if (file.size > MAX_FILE_SIZE_BYTES) return "单张图片不能超过 10 MB";
  return null;
}

export function validateImageMetadata(width: number, height: number): string | null {
  if (width <= 0 || height <= 0) return "图片尺寸无效";
  const shortSide = Math.min(width, height);
  const longSide = Math.max(width, height);
  if (shortSide < MIN_SHORT_SIDE) return "图片短边不能小于 512 px";
  if (longSide > MAX_LONG_SIDE) return "图片长边不能超过 6000 px";
  if (width * height > MAX_PIXELS) return "图片总像素不能超过 24 MP";
  if (longSide / shortSide > MAX_ASPECT_RATIO) return "图片比例必须在 1:5 到 5:1 之间";
  return null;
}

async function readImageDimensions(file: File): Promise<{ width: number; height: number }> {
  const objectUrl = URL.createObjectURL(file);
  try {
    return await new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
      image.onerror = () => reject(new ImageValidationError("无法读取图片尺寸"));
      image.src = objectUrl;
    });
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

async function sha256File(file: File): Promise<string> {
  if (!crypto.subtle) {
    throw new ImageValidationError("当前浏览器不支持 SHA-256 校验");
  }
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export async function inspectImageFile(file: File): Promise<ImageMetadata> {
  const basicError = validateFileBasics(file);
  if (basicError) throw new ImageValidationError(basicError);

  const { width, height } = await readImageDimensions(file);
  const metadataError = validateImageMetadata(width, height);
  if (metadataError) throw new ImageValidationError(metadataError);

  return {
    originalFilename: file.name,
    mimeType: file.type,
    sizeBytes: file.size,
    width,
    height,
    sha256: await sha256File(file),
  };
}