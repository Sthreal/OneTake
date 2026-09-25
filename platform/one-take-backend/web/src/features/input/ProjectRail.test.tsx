import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProjectRail } from "./ProjectRail";
import type { Project } from "./types";

const projects: Project[] = [
  {
    project_id: "prj_a",
    product_name: "项目 A",
    product_note: null,
    status: "draft",
    created_at: "2026-09-17T00:00:00Z",
    updated_at: "2026-09-17T00:00:00Z",
  },
  {
    project_id: "prj_b",
    product_name: "项目 B",
    product_note: null,
    status: "draft",
    created_at: "2026-09-16T00:00:00Z",
    updated_at: "2026-09-16T00:00:00Z",
  },
];

describe("ProjectRail", () => {
  it("renders projects and selects one", async () => {
    const onSelect = vi.fn();
    render(
      <ProjectRail
        projects={projects}
        selectedProjectId="prj_a"
        isLoading={false}
        onSelect={onSelect}
        onNew={vi.fn()}
      />,
    );
    expect(screen.getByText("项目 A")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /项目 B/ }));
    expect(onSelect).toHaveBeenCalledWith("prj_b");
  });

  it("starts a new project without removing the list", async () => {
    const onNew = vi.fn();
    render(
      <ProjectRail
        projects={projects}
        selectedProjectId="prj_a"
        isLoading={false}
        onSelect={vi.fn()}
        onNew={onNew}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /新建项目/ }));
    expect(onNew).toHaveBeenCalled();
    expect(screen.getByText("项目 A")).toBeInTheDocument();
  });
});
