import { useCallback, useEffect, useRef, useState } from "react";

import { completeAsset, listAssets, presignAsset } from "../../shared/api/assetApi";
import type { ImageMetadata, ServerAsset, UploadItem } from "./types";
import { inspectImageFile, MAX_ASSETS_PER_PROJECT } from "./validation";

const MAX_CONCURRENT_UPLOADS = 2;

function createLocalId(): string {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

function uploadFileWithProgress(
  file: File,
  uploadUrl: string,
  headers: Record<string, string>,
  onProgress: (progress: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("PUT", uploadUrl);
    Object.entries(headers).forEach(([key, value]) => request.setRequestHeader(key, value));
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) resolve();
      else reject(new Error(`上传失败（${request.status}）`));
    };
    request.onerror = () => reject(new Error("网络错误，图片上传失败"));
    request.onabort = () => reject(new Error("图片上传已取消"));
    request.send(file);
  });
}

function fromServerAsset(asset: ServerAsset): UploadItem {
  return {
    localId: `server:${asset.asset_id}`,
    source: "server",
    filename: asset.original_filename,
    mimeType: asset.mime_type,
    sizeBytes: asset.size_bytes,
    width: asset.width,
    height: asset.height,
    sha256: asset.sha256 ?? undefined,
    status: asset.status === "ready" ? "ready" : asset.status === "failed" ? "failed" : "queued",
    progress: asset.status === "ready" ? 100 : 0,
    assetId: asset.asset_id,
    objectKey: asset.object_key,
  };
}

export function useAssetUploads(projectId: string | null) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [isLoadingAssets, setIsLoadingAssets] = useState(false);
  const itemsRef = useRef<UploadItem[]>([]);
  const previewUrlsRef = useRef<string[]>([]);

  const replaceItems = useCallback((nextItems: UploadItem[]) => {
    itemsRef.current = nextItems;
    setItems(nextItems);
  }, []);

  const updateItem = useCallback((localId: string, updater: (item: UploadItem) => UploadItem) => {
    setItems((current) => {
      const next = current.map((item) => (item.localId === localId ? updater(item) : item));
      itemsRef.current = next;
      return next;
    });
  }, []);

  useEffect(() => {
    return () => {
      previewUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
      previewUrlsRef.current = [];
    };
  }, []);

  useEffect(() => {
    replaceItems([]);
    setNotice(null);
    if (!projectId) return;

    let active = true;
    setIsLoadingAssets(true);
    listAssets(projectId)
      .then((assets) => {
        if (active) replaceItems(assets.map(fromServerAsset));
      })
      .catch((error) => {
        if (active) setNotice(error instanceof Error ? error.message : "读取素材失败");
      })
      .finally(() => {
        if (active) setIsLoadingAssets(false);
      });

    return () => {
      active = false;
    };
  }, [projectId, replaceItems]);

  const addFiles = useCallback(
    async (files: File[]) => {
      if (!projectId) {
        setNotice("请先创建项目");
        return;
      }

      const currentCount = itemsRef.current.filter((item) => item.status !== "invalid").length;
      const available = Math.max(0, MAX_ASSETS_PER_PROJECT - currentCount);
      const selected = files.slice(0, available);
      setNotice(files.length > selected.length ? `当前项目最多上传 ${MAX_ASSETS_PER_PROJECT} 张图片` : null);
      if (selected.length === 0) return;

      const localItems = selected.map<UploadItem>((file) => {
        const previewUrl = URL.createObjectURL(file);
        previewUrlsRef.current.push(previewUrl);
        return {
          localId: createLocalId(),
          source: "local",
          file,
          previewUrl,
          filename: file.name,
          mimeType: file.type,
          sizeBytes: file.size,
          status: "validating",
          progress: 0,
        };
      });
      replaceItems([...itemsRef.current, ...localItems]);

      await Promise.all(
        localItems.map(async (localItem) => {
          try {
            const metadata = await inspectImageFile(localItem.file as File);
            updateItem(localItem.localId, (item) => {
              const duplicate = itemsRef.current.some(
                (candidate) =>
                  candidate.localId !== localItem.localId &&
                  candidate.sha256 === metadata.sha256 &&
                  candidate.status !== "invalid",
              );
              if (duplicate) {
                return { ...item, ...metadata, status: "invalid", error: "该图片已在当前批次中" };
              }
              return { ...item, ...metadata, status: "queued", error: undefined };
            });
          } catch (error) {
            const message = error instanceof Error ? error.message : "图片校验失败";
            updateItem(localItem.localId, (item) => ({ ...item, status: "invalid", error: message }));
          }
        }),
      );
    },
    [projectId, replaceItems, updateItem],
  );

  const uploadOne = useCallback(
    async (item: UploadItem) => {
      if (!projectId || !item.file || !item.sha256) return;
      const metadata: ImageMetadata = {
        originalFilename: item.filename,
        mimeType: item.mimeType,
        sizeBytes: item.sizeBytes,
        width: item.width as number,
        height: item.height as number,
        sha256: item.sha256,
      };

      try {
        let assetId = item.assetId;
        let objectKey = item.objectKey;

        if (!assetId || item.errorStage !== "complete") {
          updateItem(item.localId, (current) => ({ ...current, status: "presigning", error: undefined }));
          const presigned = await presignAsset(projectId, metadata);
          assetId = presigned.asset_id;
          objectKey = presigned.object_key;
          updateItem(item.localId, (current) => ({
            ...current,
            status: "uploading",
            progress: 1,
            assetId,
            objectKey,
          }));
          await uploadFileWithProgress(
            item.file,
            presigned.upload_url,
            presigned.required_headers,
            (progress) => updateItem(item.localId, (current) => ({ ...current, progress })),
          );
        }

        updateItem(item.localId, (current) => ({ ...current, status: "completing", progress: 100 }));
        const completed = await completeAsset(projectId, assetId as string, metadata);
        updateItem(item.localId, (current) => ({
          ...current,
          status: "ready",
          progress: 100,
          width: completed.width,
          height: completed.height,
          sha256: completed.sha256 ?? current.sha256,
          error: undefined,
          errorStage: undefined,
        }));
      } catch (error) {
        const message = error instanceof Error ? error.message : "上传失败";
        const stage = item.assetId ? "complete" : item.errorStage ?? "presign";
        updateItem(item.localId, (current) => ({ ...current, status: "failed", error: message, errorStage: stage }));
      }
    },
    [projectId, updateItem],
  );

  const startUploads = useCallback(async () => {
    const queued = itemsRef.current.filter((item) => item.status === "queued");
    let cursor = 0;
    let active = 0;

    await new Promise<void>((resolve) => {
      const next = () => {
        if (cursor >= queued.length && active === 0) {
          resolve();
          return;
        }
        while (active < MAX_CONCURRENT_UPLOADS && cursor < queued.length) {
          const item = queued[cursor++];
          active += 1;
          void uploadOne(item).finally(() => {
            active -= 1;
            next();
          });
        }
      };
      next();
    });
  }, [uploadOne]);

  const retryItem = useCallback(
    async (localId: string) => {
      const item = itemsRef.current.find((candidate) => candidate.localId === localId);
      if (item) await uploadOne(item);
    },
    [uploadOne],
  );

  const readyCount = items.filter((item) => item.status === "ready").length;
  const validCount = items.filter((item) => item.status !== "invalid").length;
  const isBusy = items.some((item) =>
    ["validating", "presigning", "uploading", "completing"].includes(item.status),
  );
  const hasQueued = items.some((item) => item.status === "queued");

  return {
    items,
    notice,
    isLoadingAssets,
    readyCount,
    validCount,
    isBusy,
    hasQueued,
    addFiles,
    startUploads,
    retryItem,
    setNotice,
  };
}