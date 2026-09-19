import { useCallback, useEffect, useState } from "react";
import { getContentQuality } from "../../shared/api/contentQualityApi";
import type { ContentQualityReport } from "./types";
export function useContentQuality(projectId: string | null) { const [report,setReport]=useState<ContentQualityReport|null>(null); const [isLoading,setLoading]=useState(false); const [error,setError]=useState<string|null>(null); const load=useCallback(async()=>{if(!projectId)return;setLoading(true);try{setReport(await getContentQuality(projectId));setError(null)}catch(e){setError(e instanceof Error?e.message:"读取质检结果失败")}finally{setLoading(false)}},[projectId]);useEffect(()=>{setReport(null);setError(null);if(projectId)void load()},[projectId,load]);return{report,isLoading,error,load}; }
