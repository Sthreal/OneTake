import { apiRequest } from "./client";

/** 出镜人库（人物库）：跨项目复用的**身份锚点**。
 *
 * 后端契约（apps/api/src/onetake_api/modules/character）：
 * - 母版存在**独立前缀** characters/{id}/sheet.png → 项目媒体清理（projects/{id}/）永远碰不到它，
 *   所以同一个人可以在任意项目里直接用，不再重复花钱；
 * - `source`：uploaded（用户自带照片，0 成本）/ generated（已升级成 2×2 四视角母版）；
 * - 升级四视角是**1 次付费调用**，所以按钮旁必须先把价格显示出来。
 */
export interface Character {
  character_id: string;
  name: string;
  appearance: string;
  voice_style: string | null;
  source: string;
  sheet_url: string | null;
}

export interface SheetGeneration {
  cny_per_call: number | null;
  is_mock: boolean;
}

export interface CharacterList {
  characters: Character[];
  sheet_generation: SheetGeneration;
}

export function listCharacters(): Promise<CharacterList> {
  return apiRequest<CharacterList>("/api/v1/characters");
}

export function createCharacter(input: {
  name: string;
  projectId: string;
  assetId: string;
  appearance?: string;
  voiceStyle?: string | null;
}): Promise<Character> {
  return apiRequest<Character>("/api/v1/characters", {
    method: "POST",
    body: JSON.stringify({
      name: input.name.trim(),
      project_id: input.projectId,
      asset_id: input.assetId,
      appearance: input.appearance?.trim() ?? "",
      voice_style: input.voiceStyle?.trim() || null,
    }),
  });
}

/** 升级四视角母版：**1 次付费调用**（mock 环境 0 成本），结果永久入库。 */
export function generateCharacterSheet(characterId: string): Promise<Character> {
  return apiRequest<Character>(`/api/v1/characters/${characterId}/sheet/generate`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}
