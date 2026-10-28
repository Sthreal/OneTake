import { describe, expect, it } from "vitest";

import { DEFAULT_URL_STATE, buildUrlSearch, parseUrlState, patchUrlState } from "./urlState";

describe("导演模式 URL 状态（方案 §3.1：4 步独立 URL）", () => {
  it("空地址 / 脏地址都退回默认，不抛错", () => {
    expect(parseUrlState("")).toEqual(DEFAULT_URL_STATE);
    expect(parseUrlState("?view=不存在&step=乱写&project=")).toEqual(DEFAULT_URL_STATE);
  });

  it("旧的 ?view=workbench-url 链接优雅回落到工作台（入口已删除，但不白屏）", () => {
    expect(parseUrlState("?view=workbench-url").view).toBe("workbench");
  });

  it("能解析出导演模式 + 项目 + 步骤", () => {
    expect(parseUrlState("?view=director&project=prj_1&step=compose")).toEqual({
      view: "director",
      projectId: "prj_1",
      step: "compose",
    });
  });

  it("默认值不写进 URL（工作台保持干净地址）", () => {
    expect(buildUrlSearch(DEFAULT_URL_STATE)).toBe("");
    expect(buildUrlSearch({ view: "director", projectId: "prj_1", step: "storyboard" })).toBe("view=director&project=prj_1");
    expect(buildUrlSearch({ view: "director", projectId: "prj_1", step: "delivery" })).toContain("step=delivery");
  });

  it("step 只在导演模式里进 URL（其它视图不该带它）", () => {
    expect(buildUrlSearch({ view: "projects", projectId: null, step: "compose" })).toBe("view=projects");
  });

  it("解析 / 生成可往返（同一状态稳定）", () => {
    for (const state of [
      { view: "director" as const, projectId: "prj_x", step: "assets" as const },
      { view: "projects" as const, projectId: null, step: "storyboard" as const },
      DEFAULT_URL_STATE,
    ]) {
      expect(parseUrlState(buildUrlSearch(state))).toEqual(state);
    }
  });

  it("patch 只覆盖传进来的字段", () => {
    const current = { view: "director" as const, projectId: "prj_1", step: "storyboard" as const };
    expect(patchUrlState(current, { step: "delivery" })).toEqual({
      view: "director",
      projectId: "prj_1",
      step: "delivery",
    });
  });
});
