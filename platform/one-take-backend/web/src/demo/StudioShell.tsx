/** 外壳路由。
 *
 * 默认是 iter18 浅色壳：首页上手、图片广告、品牌空间、快速出片（准备→审稿→生成→成片）。
 * 图片广告不是工作室的一步。导演模式 / 托管工作台 / 出镜人库仍走原来的深紫页面，
 * 只用 `view` 判断，避免「带了 project 就把导演模式劫持成工作台」。
 */
import { useEffect, useState } from "react";

import { CharactersPage } from "./CharactersPage";
import { DemoApp } from "./DemoApp";
import { DirectorMode } from "./DirectorMode";
import { ShellApp } from "./shell/ShellApp";
import "./studio.css";
import { isShellView, patchUrlState, pushUrlState, readUrlState, subscribeUrlState, type UrlView } from "./urlState";

type View = UrlView;

export function StudioShell() {
  const initialUrl = readUrlState();
  const [view, setView] = useState<View>(initialUrl.view);
  const [openProjectId, setOpenProjectId] = useState<string | null>(initialUrl.projectId);

  const navigate = (next: View, projectId: string | null = null) => {
    setView(next);
    setOpenProjectId(projectId);
    pushUrlState(patchUrlState(readUrlState(), { view: next, projectId }));
  };

  useEffect(() => subscribeUrlState((next) => {
    setView(next.view);
    setOpenProjectId(next.projectId);
  }), []);

  if (isShellView(view)) {
    return (
      <div className="studio ot-light">
        <ShellApp view={view} projectId={openProjectId} onNavigate={navigate} />
      </div>
    );
  }

  return (
    <div className="studio">
      <aside className="studio-side">
        <div className="studio-brand">
          <span className="studio-logo">
            <svg viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21 6 3" /></svg>
          </span>
          ONE TAKE
        </div>
        <button className="studio-item" onClick={() => navigate("home")}>首页</button>
        <div className="studio-section">创作</div>
        <button className="studio-item" onClick={() => navigate("image")}>图片广告</button>
        <button className="studio-item" onClick={() => navigate("prepare", openProjectId)}>快速出片</button>
        <button className={"studio-item" + (view === "director" ? " on" : "")} onClick={() => navigate("director", openProjectId)}>导演模式</button>
        <button className={"studio-item" + (view === "workbench" ? " on" : "")} onClick={() => navigate("workbench", openProjectId)}>托管工作台</button>
        <div className="studio-section">库</div>
        <button className="studio-item" onClick={() => navigate("projects")}>项目</button>
        <button className="studio-item" onClick={() => navigate("brand")}>品牌空间</button>
        <button className={"studio-item" + (view === "characters" ? " on" : "")} onClick={() => navigate("characters")}>出镜人</button>
        <div className="studio-spacer" />
        <p className="studio-note">快速出片不经过图片广告</p>
      </aside>
      <main className="studio-main">
        {view === "workbench" ? (
          <DemoApp
            key={openProjectId ?? view}
            initialPath="one_shot"
            initialProjectId={openProjectId}
          />
        ) : view === "director" ? (
          <DirectorMode key={openProjectId ?? "new"} projectId={openProjectId} />
        ) : (
          <CharactersPage />
        )}
      </main>
    </div>
  );
}
