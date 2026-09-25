import { useCallback, useEffect, useState } from 'react';
import { ExternalLink, RefreshCw, Video } from 'lucide-react';
import { PageHeader } from '@/components/common/PageHeader';
import { EmptyState } from '@/components/common/EmptyState';
import { Button } from '@/components/ui/button';
import { SkeletonCardList } from '@/components/common/Skeletons';
import {
  getOneTakeCapabilities,
  getOneTakeEstimate,
  getOneTakePipeline,
  getOneTakeProject,
  getOneTakeProjects,
  getOneTakeProviderStatus,
  getOneTakeVideo,
  requestOneTakeVideo,
  type OneTakeCapabilities,
  type OneTakeEstimate,
  type OneTakePipeline,
  type OneTakeProject,
  type OneTakeProvider,
  type OneTakeVideoState,
} from '@/api/onetake';

function errorText(error: unknown): string {
  if (error && typeof error === 'object' && 'message' in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) return message;
  }
  return 'One Take 服务不可用';
}

function formatDate(value?: string): string {
  if (!value) return '未记录';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN');
}

function StatusPill({ value }: { value?: string }) {
  return (
    <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
      {value || 'unknown'}
    </span>
  );
}

export function OneTakePage() {
  const [projects, setProjects] = useState<OneTakeProject[]>([]);
  const [providers, setProviders] = useState<OneTakeProvider[]>([]);
  const [capabilities, setCapabilities] = useState<OneTakeCapabilities | null>(
    null,
  );
  const [selectedId, setSelectedId] = useState('');
  const [project, setProject] = useState<OneTakeProject | null>(null);
  const [pipeline, setPipeline] = useState<OneTakePipeline | null>(null);
  const [video, setVideo] = useState<OneTakeVideoState | null>(null);
  const [estimate, setEstimate] = useState<OneTakeEstimate | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showEditor, setShowEditor] = useState(false);

  const loadProjects = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextProjects, nextProviders, nextCapabilities] =
        await Promise.all([
          getOneTakeProjects(),
          getOneTakeProviderStatus(),
          getOneTakeCapabilities(),
        ]);
      setProjects(nextProjects);
      setProviders(nextProviders);
      setCapabilities(nextCapabilities);
      setSelectedId((current) => current || nextProjects[0]?.project_id || '');
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadProject = useCallback(async (projectId: string) => {
    if (!projectId) return;
    setDetailLoading(true);
    setError(null);
    try {
      const [nextProject, nextPipeline, nextVideo] = await Promise.all([
        getOneTakeProject(projectId),
        getOneTakePipeline(projectId),
        getOneTakeVideo(projectId),
      ]);
      setProject(nextProject);
      setPipeline(nextPipeline);
      setVideo(nextVideo);
      const planId = nextVideo.plan?.plan_id;
      setEstimate(planId ? await getOneTakeEstimate(projectId, planId) : null);
    } catch (err) {
      setProject(null);
      setPipeline(null);
      setVideo(null);
      setEstimate(null);
      setError(errorText(err));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    if (selectedId) void loadProject(selectedId);
  }, [loadProject, selectedId]);

  const plan = video?.plan;

  const handleRequestVideo = async () => {
    if (!project || !plan?.plan_id) return;
    if (!window.confirm('确认真实生成视频？该操作可能产生费用。')) return;
    setError(null);
    try {
      await requestOneTakeVideo(project.project_id, plan.plan_id);
      await loadProject(project.project_id);
    } catch (err) {
      setError(errorText(err));
    }
  };

  return (
    <div className="min-h-full px-4 py-5 sm:px-6 lg:px-8 lg:py-8">
      <div className="mx-auto max-w-7xl space-y-5">
        <PageHeader
          title="商品视频"
          subtitle="只读查看 One Take 项目、生成流程、费用预估与成片状态。"
          actions={
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowEditor((value) => !value)}
              >
                {showEditor ? '关闭编辑器' : '打开专业编辑器'}
              </Button>
              <Button variant="outline" size="sm" onClick={() => void loadProjects()}>
                <RefreshCw className="mr-2 h-4 w-4" />
                刷新
              </Button>
            </>
          }
        />

        {error && (
          <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {showEditor && capabilities?.editor_url && (
          <iframe
            title="One Take 专业编辑器"
            src={capabilities.editor_url}
            className="h-[70vh] w-full rounded-2xl border border-border bg-card"
          />
        )}

        <div className="grid gap-5 lg:grid-cols-[20rem_minmax(0,1fr)]">
          <section className="rounded-2xl border border-border bg-card p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-semibold">项目</h2>
              <span className="text-xs text-muted-foreground">{projects.length} 个</span>
            </div>
            {loading ? (
              <SkeletonCardList count={4} />
            ) : projects.length === 0 ? (
              <EmptyState title="暂无项目" description="One Take 中没有可读取的项目。" />
            ) : (
              <div className="space-y-2">
                {projects.map((item) => (
                  <button
                    key={item.project_id}
                    type="button"
                    onClick={() => setSelectedId(item.project_id)}
                    className={`w-full rounded-xl border px-3 py-3 text-left transition-colors ${
                      item.project_id === selectedId
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:bg-muted/50'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">{item.product_name}</span>
                      <StatusPill value={item.status} />
                    </div>
                    <div className="mt-1 truncate text-xs text-muted-foreground">
                      {item.project_id}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>

          <section className="space-y-5">
            {detailLoading ? (
              <SkeletonCardList count={4} />
            ) : project ? (
              <>
                <div className="rounded-2xl border border-border bg-card p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="text-lg font-semibold">{project.product_name}</h2>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {project.project_id} · 更新于 {formatDate(project.updated_at)}
                      </p>
                    </div>
                    <StatusPill value={project.status} />
                  </div>
                  {project.product_note && (
                    <p className="mt-3 text-sm text-muted-foreground">{project.product_note}</p>
                  )}
                  {capabilities?.paid_enabled && plan?.plan_id && plan.status !== 'completed' && (
                    <Button className="mt-4" size="sm" onClick={() => void handleRequestVideo()}>
                      <Video className="mr-2 h-4 w-4" />
                      确认真实生成
                    </Button>
                  )}
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-2xl border border-border bg-card p-5">
                    <h3 className="font-semibold">生成流程</h3>
                    <div className="mt-3 space-y-2 text-sm">
                      <div className="flex justify-between gap-3">
                        <span className="text-muted-foreground">状态</span>
                        <StatusPill value={pipeline?.status} />
                      </div>
                      <div className="flex justify-between gap-3">
                        <span className="text-muted-foreground">当前步骤</span>
                        <span>{pipeline?.current_step ?? '未记录'}</span>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-2xl border border-border bg-card p-5">
                    <h3 className="font-semibold">视频与费用</h3>
                    <div className="mt-3 space-y-2 text-sm">
                      <div className="flex justify-between gap-3">
                        <span className="text-muted-foreground">视频状态</span>
                        <StatusPill value={plan?.status} />
                      </div>
                      <div className="flex justify-between gap-3">
                        <span className="text-muted-foreground">模式 / 时长</span>
                        <span>{plan?.mode || '未记录'} / {plan?.duration_seconds ?? '-'}s</span>
                      </div>
                      <div className="flex justify-between gap-3">
                        <span className="text-muted-foreground">预估费用</span>
                        <span>
                          {estimate?.estimated_known_cost == null
                            ? '未配置'
                            : `${estimate.currency || 'CNY'} ${estimate.estimated_known_cost}`}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="rounded-2xl border border-border bg-card p-5">
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold">Provider 状态</h3>
                    <span className="text-xs text-muted-foreground">只读</span>
                  </div>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {providers.map((provider) => (
                      <div
                        key={provider.capability}
                        className="rounded-xl border border-border px-3 py-2 text-xs"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium">{provider.capability}</span>
                          <span className={provider.ready ? 'text-emerald-600' : 'text-amber-600'}>
                            {provider.ready ? 'ready' : 'not ready'}
                          </span>
                        </div>
                        <div className="mt-1 truncate text-muted-foreground">
                          {provider.effective_provider || 'unknown'}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {plan?.video_url && (
                  <a
                    href={plan.video_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-3 text-sm font-medium hover:bg-muted"
                  >
                    <Video className="h-4 w-4" />
                    打开成片
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                )}
              </>
            ) : (
              <EmptyState title="请选择项目" description="从左侧选择项目后查看流程和成片状态。" />
            )}
          </section>
        </div>
      </div>
    </div>
  );
}