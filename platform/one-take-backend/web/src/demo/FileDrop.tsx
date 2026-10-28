/** 商品图上传区（**唯一实现**）：拖拽 + 点击上传，小白与导演模式的输入步共用。
 *
 * 为什么抽出来：出片那条的文案一直写着「把商品图拖到这里，或点击上传」，
 * 但**拖拽从来没实现**（全前端零个 `onDrop`）—— 文案承诺了不存在的能力。
 * 这里做成一份真实现，两个模式共用；同时修掉导演模式里"裸 `<input type="file">` 塞进
 * `.demo-row`"的排版问题。
 */
import { useRef, useState } from "react";

export function FileDrop({
  file,
  onPick,
  disabled = false,
}: {
  file: File | null;
  onPick: (file: File | null) => void;
  disabled?: boolean;
}) {
  const [dragging, setDragging] = useState(false);
  const [reject, setReject] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  /** 只收图片：收了别的类型会一路错到下游，所以在这里拦住并给出可读理由（不静默吞掉）。 */
  const accept = (candidate: File | null | undefined) => {
    if (!candidate) return;
    if (!candidate.type.startsWith("image/")) {
      setReject(`只支持图片文件（拿到的是 ${candidate.type || "未知类型"}）`);
      return;
    }
    setReject(null);
    onPick(candidate);
  };

  return (
    <>
      <label
        data-testid="file-drop"
        className={"demo-drop" + (file ? " has-file" : "") + (dragging ? " dragging" : "")}
        onDragOver={(event) => {
          if (disabled) return;
          event.preventDefault();   // 不 preventDefault 的话浏览器不会派发 drop
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          if (disabled) return;
          event.preventDefault();
          setDragging(false);
          accept(event.dataTransfer?.files?.[0]);
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          hidden
          disabled={disabled}
          onChange={(event) => accept(event.target.files?.[0])}
        />
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        <b>{file ? file.name : dragging ? "松手就上传" : "把商品图拖到这里，或点击上传"}</b>
        <span>支持 JPG / PNG · 白底图效果最好</span>
      </label>
      {reject ? <p className="demo-muted" style={{ color: "var(--fail, #f87171)" }}>{reject}</p> : null}
    </>
  );
}
