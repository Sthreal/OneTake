import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  test,
  vi,
} from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'routes-external-refs-'));
const tmpStoreDir = path.join(tmpDir, 'db');
const tmpGroupsDir = path.join(tmpDir, 'groups');
fs.mkdirSync(tmpStoreDir, { recursive: true });
fs.mkdirSync(tmpGroupsDir, { recursive: true });

vi.mock('../src/config.js', async () => ({
  STORE_DIR: tmpStoreDir,
  GROUPS_DIR: tmpGroupsDir,
}));

vi.mock('../src/logger.js', () => ({
  logger: { debug: () => {}, info: () => {}, warn: () => {}, error: () => {} },
}));

vi.mock('../src/middleware/auth.ts', () => ({
  authMiddleware: async (c: any, next: any) => {
    c.set('user', {
      id: process.env.MINICLAW_TEST_USER_ID ?? 'external-ref-owner',
      username: process.env.MINICLAW_TEST_USER_ID ?? 'external-ref-owner',
      role: 'member',
      permissions: [],
    });
    return next();
  },
}));

const db = await import('../src/db.js');
const routes = (await import('../src/routes/workspaces.js')).default;

const OWNER_ID = 'external-ref-owner';
const STRANGER_ID = 'external-ref-stranger';

function asUser(userId: string): void {
  process.env.MINICLAW_TEST_USER_ID = userId;
}

function createUser(id: string): void {
  const now = new Date().toISOString();
  db.createUser({
    id,
    username: id,
    password_hash: 'hash',
    display_name: id,
    role: 'member',
    status: 'active',
    created_at: now,
    updated_at: now,
    must_change_password: false,
  });
}

function registerWorkspace(jid: string, folder: string, ownerUserId: string) {
  db.setRegisteredGroup(jid, {
    name: folder,
    folder,
    added_at: new Date().toISOString(),
    created_by: ownerUserId,
    executionMode: 'host',
  });
}

beforeAll(() => {
  db.initDatabase();
  createUser(OWNER_ID);
  createUser(STRANGER_ID);
  registerWorkspace('web:external-project-a', 'external-project-a', OWNER_ID);
  registerWorkspace('web:external-project-b', 'external-project-b', OWNER_ID);
});

afterEach(() => {
  delete process.env.MINICLAW_TEST_USER_ID;
});

afterAll(() => {
  db.closeDatabase();
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

describe('/api/workspaces/external-refs', () => {
  test('binds an external project id to a workspace and is idempotent', async () => {
    asUser(OWNER_ID);
    const first = await routes.request(
      '/external-refs/onetake/prj_external_a',
      {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          workspace_jid: 'web:external-project-a',
        }),
      },
    );
    expect(first.status).toBe(201);
    const firstBody = await first.json();
    expect(firstBody.external_ref).toMatchObject({
      namespace: 'onetake',
      external_id: 'prj_external_a',
      owner_user_id: OWNER_ID,
      workspace_jid: 'web:external-project-a',
    });

    const second = await routes.request(
      '/external-refs/onetake/prj_external_a',
      {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          workspace_jid: 'web:external-project-a',
        }),
      },
    );
    expect(second.status).toBe(200);
    const secondBody = await second.json();
    expect(secondBody.external_ref.created_at).toBe(
      firstBody.external_ref.created_at,
    );

    const lookup = await routes.request(
      '/external-refs/onetake/prj_external_a',
      { method: 'GET' },
    );
    expect(lookup.status).toBe(200);
    await expect(lookup.json()).resolves.toMatchObject({
      external_ref: {
        workspace_jid: 'web:external-project-a',
      },
    });
  });

  test('rejects rebinding an external id or workspace', async () => {
    asUser(OWNER_ID);
    const sameExternal = await routes.request(
      '/external-refs/onetake/prj_external_a',
      {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          workspace_jid: 'web:external-project-b',
        }),
      },
    );
    expect(sameExternal.status).toBe(409);

    const sameWorkspace = await routes.request(
      '/external-refs/onetake/prj_external_b',
      {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          workspace_jid: 'web:external-project-a',
        }),
      },
    );
    expect(sameWorkspace.status).toBe(409);
  });

  test('keeps mappings private to the owner', async () => {
    asUser(STRANGER_ID);
    const lookup = await routes.request(
      '/external-refs/onetake/prj_external_a',
      { method: 'GET' },
    );
    expect(lookup.status).toBe(404);

    const bind = await routes.request('/external-refs/onetake/prj_external_a', {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        workspace_jid: 'web:external-project-a',
      }),
    });
    expect(bind.status).toBe(403);
  });

  test('validates namespace, external id and workspace', async () => {
    asUser(OWNER_ID);
    expect(
      (await routes.request('/external-refs/INVALID/prj', { method: 'GET' }))
        .status,
    ).toBe(400);

    expect(
      (
        await routes.request('/external-refs/onetake/missing', {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ workspace_jid: 'web:missing' }),
        })
      ).status,
    ).toBe(404);

    expect(
      (
        await routes.request('/external-refs/onetake/prj_invalid', {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ workspace_jid: 'not-a-web-workspace' }),
        })
      ).status,
    ).toBe(400);
  });
});
