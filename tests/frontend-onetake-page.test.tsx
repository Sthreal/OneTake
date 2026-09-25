// @vitest-environment happy-dom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { OneTakePage } from '../web/src/features/onetake/OneTakePage';

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

describe('One Take read-only page', () => {
  test('renders project, pipeline, estimate and output status', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/onetake/projects?limit=')) {
        return new Response(
          JSON.stringify({
            data: [
              {
                project_id: 'prj_1',
                product_name: '鲜榨杯',
                status: 'draft',
                updated_at: '2026-09-25T00:00:00.000Z',
              },
            ],
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        );
      }
      if (url.includes('/api/onetake/capabilities')) {
        return new Response(
          JSON.stringify({ data: { write_enabled: true, paid_enabled: false } }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        );
      }
      if (url.includes('/api/onetake/provider-status')) {
        return new Response(
          JSON.stringify({
            data: [
              {
                capability: 'avatar_video',
                effective_provider: 'wan-s2v',
                ready: true,
              },
            ],
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        );
      }
      if (url.includes('/api/onetake/projects/prj_1/estimate')) {
        return new Response(
          JSON.stringify({
            data: { estimated_known_cost: 16.2, currency: 'CNY' },
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        );
      }
      if (url.includes('/api/onetake/projects/prj_1/pipeline')) {
        return new Response(
          JSON.stringify({ data: { status: 'completed', current_step: 4 } }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        );
      }
      if (url.includes('/api/onetake/projects/prj_1/video')) {
        return new Response(
          JSON.stringify({
            data: {
              plan: {
                plan_id: 'vid_1',
                mode: 'avatar',
                status: 'completed',
                duration_seconds: 18,
                video_url: 'https://example.com/final.mp4',
              },
            },
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        );
      }
      if (url.includes('/api/onetake/projects/prj_1')) {
        return new Response(
          JSON.stringify({
            data: {
              project_id: 'prj_1',
              product_name: '鲜榨杯',
              status: 'draft',
              updated_at: '2026-09-25T00:00:00.000Z',
            },
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        );
      }
      throw new Error(`unexpected URL: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<OneTakePage />);
    });

    await vi.waitFor(() => {
      expect(container?.textContent).toContain('鲜榨杯');
      expect(container?.textContent).toContain('completed');
      expect(container?.textContent).toContain('CNY 16.2');
      expect(container?.textContent).toContain('打开成片');
    });
  });
});