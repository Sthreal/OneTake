import { apiRequest } from "../shared/api/client";

/** 闸口② 的前端入口：把"用户点了出片"变成一条后端可审计的批准记录。
 *  6 个付费入口都校验 cost_approvals 里有没有与当前方案 payload_hash 匹配的记录，不调就 403。 */
export interface CostApprovalResult {
  plan_id: string;
  is_paid: boolean;
  estimated_cny: number;
  payload_hash: string;
  approved_by: string;
}

export function approveCost(projectId: string, planId: string, approvedBy = "demo-ui"): Promise<CostApprovalResult> {
  return apiRequest<CostApprovalResult>(`/api/v1/projects/${projectId}/cost-approval`, {
    method: "POST",
    body: JSON.stringify({ plan_id: planId, approved_by: approvedBy }),
  });
}

export interface AutoRunData {
  run_id: string;
  project_id: string;
  status: string;
  stage: string;
  auto_run: boolean;
  auto_confirmed_stages: string[];
  auto_confirmed: string[];
  stopped_at: string | null;
  stopped_reason: string | null;
  required_action: string | null;
}

/** 自动链：只用它驱动前 4 段（识别/主图/文案/配音字幕），到闸口① 会停（设计如此）。 */
export function startAutoRun(projectId: string, fromStage?: string): Promise<AutoRunData> {
  return apiRequest<AutoRunData>(`/api/v1/projects/${projectId}/auto-run`, {
    method: "POST",
    body: JSON.stringify(fromStage ? { from_stage: fromStage } : {}),
  });
}

export function getAutoRun(runId: string): Promise<AutoRunData> {
  return apiRequest<AutoRunData>(`/api/v1/auto-runs/${runId}`);
}
