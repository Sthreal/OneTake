import { Hono } from 'hono';

import type { Variables } from '../web-context.js';
import {
  adminRoleMiddleware,
  authMiddleware,
} from '../middleware/auth.js';
import {
  createOneTakeToolRunner,
  type OneTakeToolRunner,
} from '../onetake/mcp-client.js';

const onetakeRoutes = new Hono<{ Variables: Variables }>();

let toolRunnerFactory: () => OneTakeToolRunner = createOneTakeToolRunner;

export function injectOneTakeToolRunnerFactory(
  factory: () => OneTakeToolRunner,
): void {
  toolRunnerFactory = factory;
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : 'One Take MCP 调用失败';
}

async function callTool(
  c: any,
  toolName: string,
  args: Record<string, unknown>,
) {
  try {
    const runner = toolRunnerFactory();
    const data = await runner.callTool(toolName, args);
    return c.json({ data });
  } catch (error) {
    return c.json({ error: errorMessage(error) }, 502);
  }
}

onetakeRoutes.use('*', authMiddleware, adminRoleMiddleware);

onetakeRoutes.get('/provider-status', async (c) =>
  callTool(c, 'onetake_get_provider_status', {}),
);

onetakeRoutes.get('/projects', async (c) => {
  const rawLimit = Number(c.req.query('limit') || '20');
  const limit = Number.isInteger(rawLimit)
    ? Math.min(Math.max(rawLimit, 1), 50)
    : 20;
  return callTool(c, 'onetake_list_projects', { limit });
});

onetakeRoutes.get('/projects/:projectId', async (c) =>
  callTool(c, 'onetake_get_project', {
    project_id: c.req.param('projectId'),
  }),
);

onetakeRoutes.get('/projects/:projectId/pipeline', async (c) =>
  callTool(c, 'onetake_get_pipeline', {
    project_id: c.req.param('projectId'),
  }),
);

onetakeRoutes.get('/projects/:projectId/video', async (c) =>
  callTool(c, 'onetake_get_video', {
    project_id: c.req.param('projectId'),
  }),
);

onetakeRoutes.get('/projects/:projectId/estimate', async (c) => {
  const planId = c.req.query('planId');
  if (!planId) {
    return c.json({ error: 'planId is required' }, 400);
  }
  return callTool(c, 'onetake_estimate_video_cost', {
    project_id: c.req.param('projectId'),
    plan_id: planId,
  });
});

export default onetakeRoutes;