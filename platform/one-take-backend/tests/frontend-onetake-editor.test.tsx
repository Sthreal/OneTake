// @vitest-environment happy-dom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { OneTakeEditor } from '../packages/onetake-editor/src/OneTakeEditor';

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(() => {
  vi.unstubAllGlobals();
  if (root) act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

describe('One Take native editor', () => {
  test('renders editor state and confirms main image', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/editor') && (!init?.method || init.method === 'GET')) {
        return new Response(
          JSON.stringify({
            data: {
              mainImage: {
                version: { status: 'ready', png_url: 'https://example.com/main.png' },
              },
              script: {
                version: {
                  status: 'ready',
                  hook: 'Hook',
                  pain_point: 'Pain',
                  selling_points: ['Point'],
                  usage_scenario: 'Scene',
                  cta: 'CTA',
                },
              },
              subtitle: {
                version: { status: 'ready', segments: [{ index: 0, text: '字幕' }] },
              },
              video: { plan: null },
            },
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        );
      }
      if (url.includes('/main-image/confirm')) {
        return new Response(JSON.stringify({ data: {} }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      }
      throw new Error(`unexpected URL: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<OneTakeEditor projectId="prj_1" />);
    });

    await vi.waitFor(() => {
      expect(container?.textContent).toContain('主图');
      expect(container?.textContent).toContain('文案');
      expect(container?.textContent).toContain('字幕');
      expect(container?.textContent).toContain('视频方案');
      expect(container?.textContent).toContain('确认主图');
    });

    const confirm = Array.from(container!.querySelectorAll('button')).find(
      (button) => button.textContent?.includes('确认主图'),
    );
    await act(async () => {
      confirm?.click();
    });
    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/main-image/confirm'))).toBe(true);
    });
  });
});