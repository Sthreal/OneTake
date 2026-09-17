import type { Project } from "./types";

interface ProjectRailProps {
  projects: Project[];
  selectedProjectId: string | null;
  isLoading: boolean;
  onSelect: (projectId: string) => void;
  onNew: () => void;
}

function formatProjectTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function ProjectRail({
  projects,
  selectedProjectId,
  isLoading,
  onSelect,
  onNew,
}: ProjectRailProps) {
  return (
    <aside className="project-rail">
      <div className="rail-heading">
        <span>项目</span>
        <span>{projects.length}</span>
      </div>
      <button className="new-project-button" type="button" onClick={onNew}>
        <span aria-hidden="true">＋</span>
        新建项目
      </button>

      <div className="rail-label">最近项目</div>
      <div className="project-list">
        {isLoading ? (
          <div className="rail-empty"><span className="spinner small" />读取项目</div>
        ) : projects.length ? (
          projects.map((project) => (
            <button
              className={"project-item " + (project.project_id === selectedProjectId ? "is-selected" : "")}
              type="button"
              key={project.project_id}
              onClick={() => onSelect(project.project_id)}
            >
              <span className="project-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none">
                  <path d="M4 7.5A2.5 2.5 0 0 1 6.5 5h3l2 2h6A2.5 2.5 0 0 1 20 9.5v7A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5v-9Z" />
                </svg>
              </span>
              <span className="project-copy">
                <strong>{project.product_name}</strong>
                <small>{formatProjectTime(project.updated_at)}</small>
              </span>
              <span className="project-state-dot" aria-hidden="true" />
            </button>
          ))
        ) : (
          <div className="rail-empty">
            <strong>暂无项目</strong>
            <p>创建后会自动出现在这里。</p>
          </div>
        )}
      </div>
    </aside>
  );
}
