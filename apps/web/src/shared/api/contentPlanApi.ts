import type { ContentPlan, ContentScene } from "../../features/content-plan/types";
import { apiRequest } from "./client";
export const getContentPlan=(id:string)=>apiRequest<ContentPlan|null>(`/api/v1/projects/${id}/content-plan`);
export const generateContentPlan=(id:string)=>apiRequest<ContentPlan>(`/api/v1/projects/${id}/content-plan`,{method:"POST"});
export const updateContentPlan=(id:string,index:number,scenes:ContentScene[])=>apiRequest<ContentPlan>(`/api/v1/projects/${id}/content-plan`,{method:"PATCH",body:JSON.stringify({selected_variant_index:index,scenes})});
export const confirmContentPlan=(id:string)=>apiRequest<ContentPlan>(`/api/v1/projects/${id}/content-plan/confirm`,{method:"POST"});
