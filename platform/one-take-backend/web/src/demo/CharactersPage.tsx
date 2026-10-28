/** 出镜人库页面（库 → 出镜人）。
 *
 * 对应用户的问题：「花钱生成的人物能沉淀到人物库里、下次接着直接用吗」
 * → 能：母版存在 **characters/ 独立前缀**（不属于任何项目），项目只引用 character_id，
 *   所以任何项目选这个人都是 0 额外成本；升级四视角只花**一次**钱。
 *
 * 风格要求（用户明确）：简约、卡片式、只用现有 token（--pu/--grad/--done/--warn/--line/--muted/--txt），
 * 不引入新的视觉语言。
 */
import { useCallback, useEffect, useState } from "react";

import { completeAsset, presignAsset } from "../shared/api/assetApi";
import { createCharacter, generateCharacterSheet, listCharacters, type CharacterList } from "../shared/api/characterApi";
import { inspectImageFile } from "../features/input/validation";
import { listProjects } from "../shared/api/projectApi";

export function CharactersPage() {
  const [data, setData] = useState<CharacterList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [projects, setProjects] = useState<{ project_id: string; product_name: string }[]>([]);
  const [hostProjectId, setHostProjectId] = useState("");
  const [name, setName] = useState("");
  const [appearance, setAppearance] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, projectList] = await Promise.all([listCharacters(), listProjects(20)]);
      setData(list);
      setProjects(projectList);
      setHostProjectId((current) => current || projectList[0]?.project_id || "");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取人物库失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const priceText = () => {
    if (!data) return "";
    if (data.sheet_generation.is_mock) return "0 元（mock 环境）";
    if (data.sheet_generation.cny_per_call === null) return "单价未配置";
    return `¥${data.sheet_generation.cny_per_call}`;
  };

  async function createNew() {
    if (!file || !name.trim() || !hostProjectId) return;
    setBusy("create");
    setError(null);
    try {
      // 照片先按普通素材上传到某个项目（只为拿一个可读的对象键），
      // 随后后端会把它复制到 characters/{id}/sheet.png 永久留存。
      const metadata = await inspectImageFile(file);
      const presigned = await presignAsset(hostProjectId, metadata);
      const put = await fetch(presigned.upload_url, {
        method: "PUT",
        headers: presigned.required_headers ?? {},
        body: file,
      });
      if (!put.ok) throw new Error(`照片上传失败（${put.status}）`);
      await completeAsset(hostProjectId, presigned.asset_id, metadata);
      const character = await createCharacter({
        name,
        projectId: hostProjectId,
        assetId: presigned.asset_id,
        appearance,
      });
      setNote(`已入库：${character.name}（${character.character_id}）—— 以后任何项目都能直接用这个人。`);
      setName("");
      setAppearance("");
      setFile(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "新建出镜人失败");
    } finally {
      setBusy(null);
    }
  }

  async function upgrade(characterId: string, characterName: string) {
    const ok = window.confirm(
      `把「${characterName}」升级成 2×2 四视角母版？\n\n· 这是一次付费调用：${priceText()}（只花这一次）\n· 原照片会留在人物库里，可反复重跑\n· 升级后母版永久入库，任何项目复用都不再花钱`,
    );
    if (!ok) return;
    setBusy(characterId);
    setError(null);
    setNote("正在生成四视角母版（大约 30 秒～2 分钟）…");
    try {
      await generateCharacterSheet(characterId);
      setNote(`「${characterName}」已升级成四视角母版，已永久入库。`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "升级失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="studio-page">
      <h1>出镜人</h1>
      <p className="studio-note" style={{ padding: 0, marginBottom: 16 }}>
        入库一次、跨项目复用。母版存人物库独立前缀，项目媒体清理不会删它。
      </p>
      {error ? <p className="studio-error">{error}</p> : null}
      {note ? <p className="studio-hint">{note}</p> : null}

      <div className="studio-card">
        <h2>新建出镜人（0 成本）</h2>
        <div className="studio-form">
          <input className="studio-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="名字（例如：小夏）" />
          <input className="studio-input" value={appearance} onChange={(e) => setAppearance(e.target.value)} placeholder="外貌锚点（选填，例如：短发、米色上衣）" />
          <label className="studio-upload">
            <input type="file" accept="image/*" hidden onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            {file ? file.name : "选择照片（真人正脸，白底或浅色背景最好）"}
          </label>
          <select className="studio-input" value={hostProjectId} onChange={(e) => setHostProjectId(e.target.value)}>
            {projects.length === 0 ? <option value="">（先建一个项目，照片要借它暂存）</option> : null}
            {projects.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                照片暂存到：{project.product_name}
              </option>
            ))}
          </select>
          <button className="studio-btn" disabled={busy !== null || !file || !name.trim() || !hostProjectId} onClick={() => void createNew()}>
            {busy === "create" ? "入库中…" : "入库"}
          </button>
        </div>
      </div>

      <h2 className="studio-h2">人物库（{data?.characters.length ?? 0}）</h2>
      {data && data.characters.length === 0 ? <p className="studio-note" style={{ padding: 0 }}>还没有出镜人。</p> : null}
      <div className="studio-cards">
        {(data?.characters ?? []).map((character) => (
          <div className="studio-card studio-person" key={character.character_id}>
            {character.sheet_url ? (
              <img className="studio-thumb" src={character.sheet_url} alt={character.name} />
            ) : (
              <div className="studio-thumb studio-thumb-empty">母版读取失败</div>
            )}
            <b>{character.name}</b>
            <span className={`studio-badge ${character.source === "generated" ? "ok" : ""}`}>
              {character.source === "generated" ? "四视角母版" : "原始照片"}
            </span>
            <small>{character.appearance || "（没写外貌锚点）"}</small>
            <small>{character.character_id}</small>
            {character.source === "generated" ? (
              <button className="studio-btn" disabled={busy !== null} onClick={() => void upgrade(character.character_id, character.name)}>
                重新生成一次（{priceText()}）
              </button>
            ) : (
              <button className="studio-btn primary" disabled={busy !== null} onClick={() => void upgrade(character.character_id, character.name)}>
                {busy === character.character_id ? "生成中…" : `升级四视角母版（${priceText()}）`}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
