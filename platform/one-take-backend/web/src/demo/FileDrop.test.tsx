import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FileDrop } from "./FileDrop";

const image = () => new File(["x"], "商品图.png", { type: "image/png" });

describe("商品图上传区（拖拽是**真实现**，不只是文案）", () => {
  it("拖入图片 → 回调真的拿到该文件", () => {
    const onPick = vi.fn();
    render(<FileDrop file={null} onPick={onPick} />);
    const zone = screen.getByTestId("file-drop");
    fireEvent.dragOver(zone);
    expect(screen.getByText("松手就上传")).toBeInTheDocument();   // 拖拽态可见
    const file = image();
    fireEvent.drop(zone, { dataTransfer: { files: [file] } });
    expect(onPick).toHaveBeenCalledWith(file);
  });

  it("拖入非图片 → 不冒充成功，给出可读理由", () => {
    const onPick = vi.fn();
    render(<FileDrop file={null} onPick={onPick} />);
    fireEvent.drop(screen.getByTestId("file-drop"), {
      dataTransfer: { files: [new File(["x"], "说明.txt", { type: "text/plain" })] },
    });
    expect(onPick).not.toHaveBeenCalled();
    expect(screen.getByText(/只支持图片文件/)).toBeInTheDocument();
  });

  it("已经有文件时显示文件名；点选通道（hidden input）仍在", () => {
    const onPick = vi.fn();
    render(<FileDrop file={image()} onPick={onPick} />);
    expect(screen.getByText("商品图.png")).toBeInTheDocument();
    expect(screen.getByTestId("file-drop").querySelector("input[type=file]")).not.toBeNull();
  });
});
