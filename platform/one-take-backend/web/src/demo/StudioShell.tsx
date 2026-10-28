/** 外壳：**两段式左侧边栏**（创作 / 库）。
 *
 * 形态参考 ClipForge 的导航分组（`src/components/app-shell.tsx:29-48`：两段 + 底部设置），
 * 但**每一条都映射到我们真实具备的能力** —— 没有后端的一律标"待做"、不做可点的假入口：
 * - 创作：出片（主路，页内自带「上传商品图 / 商品链接」两个 tab）· 导演模式
 * - 库：项目（`GET /projects`）· 出镜人（`GET /characters`，跨项目复用的人物库；数字人档位已下线，但**人物库**是另一回事）
 * - 真实能力：**导演模式**（逐镜生成，走 /video/batch 步进 + S6 的质量/接缝/预检端点；2026-10-15）
 *   —— 原先挂在这里的「批量出片」是**借了名字的假入口**（点了只是把工作台切到分段路径），已删除
 * - 待做（用户明确同意"先摆上、后面补"）：爆款复刻 / 商品库 / 出镜人（已下线） / 全过程（9 段控制台，B4）
 *   这一组统一用不可点的灰字标出，避免出现"有按钮没后端"。
 */
import { useCallback, useEffect, useState } from "react";

import { CharactersPage } from "./CharactersPage";
import { DemoApp } from "./DemoApp";
import { DirectorMode } from "./DirectorMode";
import "./studio.css";
import { listProjects } from "../shared/api/projectApi";
import { patchUrlState, pushUrlState, readUrlState, subscribeUrlState, type UrlView } from "./urlState";

type View = UrlView;
const projectView = (id: string) => `project:${id}`;

export function StudioShell() {
  // ① URL 化：初始视图/项目从地址栏恢复（可分享、可刷新、可后退）
  const initialUrl = readUrlState();
  const [view, setView] = useState<View>(initialUrl.view);
  const [openProjectId, setOpenProjectId] = useState<string | null>(initialUrl.projectId);
  const [projects, setProjects] = useState<{ project_id: string; product_name: string; created_at: string }[]>([]);
  const [projectsError, setProjectsError] = useState<string | null>(null);

  /** ① URL 化（方案 §3.1）：所有视图切换都写进地址栏 —— 可分享、可刷新、可后退。 */
  const navigate = (next: View, projectId: string | null = null) => {
    setView(next);
    setOpenProjectId(projectId);
    pushUrlState(patchUrlState(readUrlState(), { view: next, projectId }));
  };

  // 浏览器后退 / 前进：把视图与项目同步回来（步骤由 DirectorMode 自己订阅）
  useEffect(() => subscribeUrlState((next) => {
    setView(next.view);
    setOpenProjectId(next.projectId);
  }), []);

  const loadProjects = useCallback(async () => {
    try {
      setProjects(await listProjects(20));
      setProjectsError(null);
    } catch (error) {
      setProjectsError(error instanceof Error ? error.message : "读取项目失败");
    }
  }, []);

  useEffect(() => {
    // 导演模式的项目选择器也用这份列表 —— 只在 projects 视图加载会让它**永远是空列表**（S4 漏的）
    if (view === "projects" || view === "director") void loadProjects();
  }, [loadProjects, view]);

  // ⚠️ 判据只能用 `view`：**导演模式也带项目** —— 曾经把 `openProjectId !== null` 也算进工作台，
  // 结果 `view=director` + 有项目时被劫持成工作台，**导演模式整页进不去**（2026-10-15 实测踩过）。
  const isWorkbench = view === "workbench";

  return (
    <div className="studio">
      <aside className="studio-side">
        <div className="studio-brand">
          <span className="studio-logo">
            <svg viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21 6 3" /></svg>
          </span>
          ONE TAKE
        </div>
        <div className="studio-section">创作</div>
        <button className={"studio-item" + (view === "workbench" && !openProjectId ? " on" : "")} onClick={() => navigate("workbench")}>
          出片
        </button>
        <button className={"studio-item" + (view === "director" ? " on" : "")} onClick={() => navigate("director")}>
          导演模式
        </button>
        <span className="studio-todo-item" title="按参考视频复刻分镜：需要新的解析能力，后端尚无（待做）">爆款复刻 · 待做</span>
        <div className="studio-section">库</div>
        <button className={"studio-item" + (view === "projects" && !openProjectId ? " on" : "")} onClick={() => navigate("projects")}>
          项目
        </button>
        <span className="studio-todo-item" title="商品库：后端尚无跨项目的商品实体（待做）">商品库 · 待做</span>
        <button className={"studio-item" + (view === "characters" && !openProjectId ? " on" : "")} onClick={() => navigate("characters")}>
          出镜人
        </button>
        <span className="studio-todo-item" title="9 段 3 闸控制台（待做 B4）">全过程 · 待做</span>
        <div className="studio-spacer" />
        <p className="studio-note">商品图 → 2 次点击 → 成片</p>
      </aside>
      <main className="studio-main">
        {isWorkbench ? (
          <DemoApp
            key={openProjectId ?? view}
            initialPath="one_shot"
            initialProjectId={openProjectId}
          />
        ) : view === "director" ? (
          // 导演模式与小白**并存**：它自己就能输入（商品图/链接），所以没有项目也直接进
          <DirectorMode key={openProjectId ?? "new"} projectId={openProjectId} />
        ) : view === "characters" ? (
          <CharactersPage />
        ) : (
          <div className="studio-page">
            <h1>项目</h1>
            {projectsError ? <p className="studio-error">{projectsError}</p> : null}
            {projects.length === 0 && !projectsError ? <p className="studio-note">还没有项目。回「出片」做第一条。</p> : null}
            <ul className="studio-projects">
              {projects.map((project) => (
                <li key={project.project_id}>
                  <button className="studio-item studio-project-open" onClick={() => navigate("workbench", project.project_id)}>
                    打开（看进度 / 继续出片）
                  </button>
                  <button className="studio-item studio-project-open" onClick={() => navigate("director", project.project_id)}>
                    进导演模式（逐镜可控）
                  </button>
                  <b>{project.product_name}</b>
                  <small>{project.project_id}</small>
                  <small>{new Date(project.created_at).toLocaleString()}</small>
                </li>
              ))}
            </ul>
          </div>
        )}
      </main>
    </div>
  );
}
