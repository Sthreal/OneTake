import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

import {
  ONETAKE_MCP_APPROVAL_TOKEN,
  ONETAKE_MCP_TOKEN,
  ONETAKE_MCP_URL,
} from '../config.js';

export interface OneTakeToolRunner {
  callTool(name: string, args: Record<string, unknown>): Promise<unknown>;
}

function parseToolResult(result: unknown): unknown {
  if (!result || typeof result !== 'object') return result;
  const record = result as {
    content?: Array<{ type?: string; text?: string }>;
    isError?: boolean;
  };
  const textBlocks = (record.content ?? [])
    .filter((item) => item.type === 'text' && typeof item.text === 'string')
    .map((item) => item.text as string);
  if (record.isError) {
    throw new Error(textBlocks.join('\n') || 'One Take MCP tool failed');
  }
  const parsed = textBlocks.map((text) => {
    try {
      return JSON.parse(text) as unknown;
    } catch {
      return text;
    }
  });
  if (parsed.length === 1) return parsed[0];
  return parsed;
}

export function createOneTakeToolRunner(): OneTakeToolRunner {
  if (!ONETAKE_MCP_TOKEN) {
    throw new Error('ONETAKE_MCP_TOKEN is not configured');
  }
  return {
    async callTool(name, args) {
      const transport = new StreamableHTTPClientTransport(
        new URL(ONETAKE_MCP_URL),
        {
          requestInit: {
            headers: { Authorization: `Bearer ${ONETAKE_MCP_TOKEN}` },
          },
        },
      );
      const client = new Client({
        name: 'miniclaw-onetake',
        version: '1.0.0',
      });
      try {
        await client.connect(transport);
        const result = await client.callTool({ name, arguments: args });
        return parseToolResult(result);
      } finally {
        await client.close().catch(() => undefined);
      }
    },
  };
}

export async function runOneTakeTool(
  name: string,
  args: Record<string, unknown>,
): Promise<unknown> {
  return createOneTakeToolRunner().callTool(name, args);
}

export async function createOneTakeApproval(input: {
  action: 'voice' | 'video';
  projectId: string;
  planId?: string;
  summary: string;
}): Promise<{
  approval_id: string;
  action: string;
  target: string;
  expires_at: number;
}> {
  if (!ONETAKE_MCP_APPROVAL_TOKEN) {
    throw new Error('ONETAKE_MCP_APPROVAL_TOKEN is not configured');
  }
  const approvalUrl = new URL(ONETAKE_MCP_URL);
  approvalUrl.pathname = approvalUrl.pathname.replace(
    /\/mcp\/?$/,
    '/internal/approvals',
  );
  const response = await fetch(approvalUrl, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${ONETAKE_MCP_APPROVAL_TOKEN}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      action: input.action,
      project_id: input.projectId,
      plan_id: input.planId,
      summary: input.summary,
    }),
  });
  const payload = (await response.json().catch(() => ({}))) as Record<
    string,
    unknown
  >;
  if (!response.ok) {
    throw new Error(
      String(payload.detail || `Approval failed: HTTP ${response.status}`),
    );
  }
  return payload as {
    approval_id: string;
    action: string;
    target: string;
    expires_at: number;
  };
}