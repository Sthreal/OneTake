import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, test } from 'vitest';

const root = process.cwd();
const read = (relativePath: string) =>
  fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('product terminology', () => {
  test('uses 智能体 for the top-level product concept', () => {
    const productSurface = [
      'web-miniclaw/src/components/layout/nav-items.ts',
      'web-miniclaw/src/components/layout/UnifiedSidebar.tsx',
      'web-miniclaw/src/pages/ChatPage.tsx',
      'web-miniclaw/src/pages/AgentProfilesPage.tsx',
      'web-miniclaw/src/components/chat/CreateContainerDialog.tsx',
      'web-miniclaw/src/pages/UsagePage.tsx',
      'web-miniclaw/src/pages/SettingsPage.tsx',
    ]
      .map(read)
      .join('\n');

    expect(productSurface).toContain("label: '智能体'");
    expect(productSurface).toContain('主智能体');
    expect(productSurface).toContain('自定义智能体');
    expect(productSurface).toContain('为智能体新建工作区');
    expect(productSurface).toContain('智能体运行次数');
    expect(productSurface).not.toMatch(
      /label: 'Agent'|主 Agent|自定义 Agent|Agent 工作区|选择 Agent|创建 Agent|Agent 运行次数|Agent 列表/,
    );
  });

  test('keeps Pi runtime and subagent terminology technically explicit', () => {
    const login = read('web-miniclaw/src/pages/LoginPage.tsx');
    const streaming = read('web-miniclaw/src/components/chat/StreamingDisplay.tsx');
    const workflow = read('web-miniclaw/src/components/chat/WorkflowRunCard.tsx');
    const tools = read('web-miniclaw/src/components/chat/ToolActivityCard.tsx');
    const readme = read('README.md');

    expect(login).toContain('Powered by Pi Agent Runtime');
    expect(streaming).toContain('子 Agent:');
    expect(workflow).toContain('个 Agent');
    expect(tools).toContain("case 'Agent':");
    expect(readme).toContain('Pi Agent Runtime');
    expect(readme).toContain('智能体优先工作模型');
  });
});
