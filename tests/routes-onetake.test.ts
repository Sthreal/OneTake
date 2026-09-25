import { Hono } from 'hono';
import { beforeEach, describe, expect, test, vi } from 'vitest';

const calls: Array<{ name: string; args: Record<string, unknown> }> = [];

vi.mock('../src/middleware/auth.ts', () => ({
  authMiddleware: async (c: any, next: any) => {
    c.set('user', {
      id: c.req.header('x-test-user') || 'admin',
      username: 'test',
      role: c.req.header('x-test-role') || 'admin',
      status: 'active',
      permissions: [],
      must_change_password: false,
    });
    return next();
  },
  adminRoleMiddleware: async (c: any, next: any) => {
    if (c.get('user').role !== 'admin') {
      return c.json({ error: 'Forbidden: admin role required' }, 403);
    }
    return next();
  },
}));

const { default: routes, injectOneTakeToolRunnerFactory } = await import(
  '../src/routes/onetake.js'
);
const app = new Hono().route('/api/onetake', routes);

beforeEach(() => {
  calls.length = 0;
  injectOneTakeToolRunnerFactory(() => ({
    async callTool(name, args) {
      calls.push({ name, args });
      if (name === 'onetake_get_provider_status') {
        return [{ capability: 'avatar_video', ready: true }];
      }
      return { ok: true };
    },
  }));
});

describe('One Take read-only routes', () => {
  test('admin can list projects', async () => {
    const response = await app.request('/api/onetake/projects?limit=10', {
      headers: { 'x-test-role': 'admin' },
    });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ data: { ok: true } });
    expect(calls).toEqual([
      { name: 'onetake_list_projects', args: { limit: 10 } },
    ]);
  });

  test('member cannot access One Take routes', async () => {
    const response = await app.request('/api/onetake/projects', {
      headers: { 'x-test-role': 'member' },
    });
    expect(response.status).toBe(403);
    expect(calls).toEqual([]);
  });

  test('estimate requires planId', async () => {
    const response = await app.request('/api/onetake/projects/prj_1/estimate', {
      headers: { 'x-test-role': 'admin' },
    });
    expect(response.status).toBe(400);
  });

  test('provider status is exposed as a read-only route', async () => {
    const response = await app.request('/api/onetake/provider-status', {
      headers: { 'x-test-role': 'admin' },
    });
    expect(response.status).toBe(200);
    expect(calls[0]).toEqual({
      name: 'onetake_get_provider_status',
      args: {},
    });
  });
});