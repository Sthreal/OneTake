import { Hono } from 'hono';

import type { Variables } from '../web-context.js';
import { ONETAKE_EDITOR_URL } from '../config.js';
import {
  adminRoleMiddleware,
  authMiddleware,
} from '../middleware/auth.js';
import {
  confirmOneTakeAudioSubtitle,
  confirmOneTakeMainImage,
  confirmOneTakeScript,
  createOneTakeVideoPlan,
  loadOneTakeEditorState,
  updateOneTakeScript,
  updateOneTakeSubtitle,
} from '../onetake/editor-client.js';
import {
  createOneTakeApproval,
  createOneTakeToolRunner,
  runOneTakeTool,
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

onetakeRoutes.get('/capabilities', async (c) => {
  try {
    const data = await createOneTakeToolRunner().callTool(
      'onetake_get_mcp_capabilities',
      {},
    );
    return c.json({
      data: {
        ...(typeof data === 'object' && data ? data : {}),
        editor_url: ONETAKE_EDITOR_URL,
      },
    });
  } catch (error) {
    return c.json({ error: errorMessage(error) }, 502);
  }
});

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

onetakeRoutes.post('/projects/:projectId/request-video', async (c) => {
  const payload = await c.req.json().catch(() => ({}));
  const planId = String(payload.plan_id || '');
  if (!planId) {
    return c.json({ error: 'plan_id is required' }, 400);
  }
  const projectId = c.req.param('projectId');
  try {
    const approval = await createOneTakeApproval({
      action: 'video',
      projectId,
      planId,
      summary: `生成项目 ${projectId} 的视频 ${planId}`,
    });
    const data = await runOneTakeTool('onetake_request_video', {
      project_id: projectId,
      plan_id: planId,
      approval_id: approval.approval_id,
    });
    return c.json({ data });
  } catch (error) {
    return c.json({ error: errorMessage(error) }, 502);
  }
});


onetakeRoutes.get('/projects/:projectId/editor', async (c) => {
  try {
    return c.json({
      data: await loadOneTakeEditorState(c.req.param('projectId')),
    });
  } catch (error) {
    return c.json({ error: errorMessage(error) }, 502);
  }
});

onetakeRoutes.post('/projects/:projectId/main-image/confirm', async (c) => {
  try {
    return c.json({
      data: await confirmOneTakeMainImage(c.req.param('projectId')),
    });
  } catch (error) {
    return c.json({ error: errorMessage(error) }, 502);
  }
});

onetakeRoutes.patch('/projects/:projectId/script', async (c) => {
  try {
    const payload = await c.req.json();
    return c.json({
      data: await updateOneTakeScript(c.req.param('projectId'), payload),
    });
  } catch (error) {
    return c.json({ error: errorMessage(error) }, 502);
  }
});

onetakeRoutes.post('/projects/:projectId/script/confirm', async (c) => {
  try {
    return c.json({
      data: await confirmOneTakeScript(c.req.param('projectId')),
    });
  } catch (error) {
    return c.json({ error: errorMessage(error) }, 502);
  }
});

onetakeRoutes.patch('/projects/:projectId/subtitle', async (c) => {
  try {
    const payload = await c.req.json();
    return c.json({
      data: await updateOneTakeSubtitle(
        c.req.param('projectId'),
        Array.isArray(payload.segments) ? payload.segments : [],
      ),
    });
  } catch (error) {
    return c.json({ error: errorMessage(error) }, 502);
  }
});

onetakeRoutes.post('/projects/:projectId/audio-subtitle/confirm', async (c) => {
  try {
    return c.json({
      data: await confirmOneTakeAudioSubtitle(c.req.param('projectId')),
    });
  } catch (error) {
    return c.json({ error: errorMessage(error) }, 502);
  }
});

onetakeRoutes.post('/projects/:projectId/video-plan', async (c) => {
  try {
    const payload = await c.req.json();
    const mode = payload.mode === 'product' ? 'product' : 'avatar';
    return c.json({
      data: await createOneTakeVideoPlan(
        c.req.param('projectId'),
        mode,
        payload.template_id,
      ),
    });
  } catch (error) {
    return c.json({ error: errorMessage(error) }, 502);
  }
});
export default onetakeRoutes;