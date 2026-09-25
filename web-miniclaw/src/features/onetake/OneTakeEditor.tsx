import { useCallback, useEffect, useState } from 'react';
import { Check, Image as ImageIcon, Save, Video } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { SkeletonCardList } from '@/components/common/Skeletons';
import {
  confirmOneTakeAudioSubtitle,
  confirmOneTakeMainImage,
  confirmOneTakeScript,
  createOneTakeVideoPlan,
  loadOneTakeEditorState,
  requestOneTakeVoice,
  updateOneTakeScript,
  updateOneTakeSubtitle,
  type OneTakeEditorState,
} from '@/api/onetake';

interface SubtitleSegment {
  index: number;
  text: string;
}

function errorText(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : '编辑器操作失败';
}

export function OneTakeEditor({ projectId }: { projectId: string }) {
  const [state, setState] = useState<OneTakeEditorState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scriptDraft, setScriptDraft] = useState({
    hook: '',
    pain_point: '',
    selling_points: '',
    usage_scenario: '',
    cta: '',
  });
  const [subtitleDraft, setSubtitleDraft] = useState<SubtitleSegment[]>([]);
  const [videoMode, setVideoMode] = useState<'avatar' | 'product'>('avatar');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await loadOneTakeEditorState(projectId);
      setState(next);
      const script = (next.script?.version ?? {}) as Record<string, any>;
      setScriptDraft({
        hook: String(script.hook ?? ''),
        pain_point: String(script.pain_point ?? ''),
        selling_points: Array.isArray(script.selling_points)
          ? script.selling_points.join('\n')
          : '',
        usage_scenario: String(script.usage_scenario ?? ''),
        cta: String(script.cta ?? ''),
      });
      const subtitle = (next.subtitle?.version ?? {}) as Record<string, any>;
      setSubtitleDraft(
        Array.isArray(subtitle.segments)
          ? subtitle.segments.map((segment: any, index: number) => ({
              index: Number(segment.index ?? index),
              text: String(segment.text ?? ''),
            }))
          : [],
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (operation: () => Promise<unknown>) => {
    setError(null);
    try {
      await operation();
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  };

  if (loading) return <SkeletonCardList count={4} />;
  if (!state) return null;

  const mainImage = (state.mainImage?.version ?? {}) as Record<string, any>;
  const script = (state.script?.version ?? {}) as Record<string, any>;
  const subtitle = (state.subtitle?.version ?? {}) as Record<string, any>;
  const video = (state.video?.plan ?? {}) as Record<string, any>;

  return (
    <div className="space-y-5">
      {error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <section className="rounded-2xl border border-border bg-card p-5">
        <div className="flex items-center justify-between gap-3">
          <h3 className="flex items-center gap-2 font-semibold">
            <ImageIcon className="h-4 w-4" />
            主图
          </h3>
          {mainImage.status !== 'confirmed' && (
            <Button size="sm" onClick={() => void run(() => confirmOneTakeMainImage(projectId))}>
              <Check className="mr-2 h-4 w-4" />
              确认主图
            </Button>
          )}
        </div>
        {mainImage.png_url || mainImage.jpg_url ? (
          <img
            src={mainImage.png_url || mainImage.jpg_url}
            alt="One Take 主图"
            className="mt-4 max-h-96 rounded-xl border border-border object-contain"
          />
        ) : (
          <p className="mt-3 text-sm text-muted-foreground">主图尚未生成</p>
        )}
      </section>

      <section className="rounded-2xl border border-border bg-card p-5">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-semibold">文案</h3>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                void run(() =>
                  updateOneTakeScript(projectId, {
                    hook: scriptDraft.hook,
                    pain_point: scriptDraft.pain_point,
                    selling_points: scriptDraft.selling_points
                      .split('\n')
                      .map((item) => item.trim())
                      .filter(Boolean),
                    usage_scenario: scriptDraft.usage_scenario,
                    cta: scriptDraft.cta,
                  }),
                )
              }
            >
              <Save className="mr-2 h-4 w-4" />
              保存
            </Button>
            <Button size="sm" onClick={() => void run(() => confirmOneTakeScript(projectId))}>
              确认文案
            </Button>
          </div>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {(['hook', 'pain_point', 'usage_scenario', 'cta'] as const).map((key) => (
            <label key={key} className="space-y-1 text-sm">
              <span className="text-muted-foreground">{key}</span>
              <textarea
                className="min-h-20 w-full rounded-xl border border-border bg-background px-3 py-2"
                value={scriptDraft[key]}
                onChange={(event) =>
                  setScriptDraft((draft) => ({ ...draft, [key]: event.target.value }))
                }
              />
            </label>
          ))}
          <label className="space-y-1 text-sm md:col-span-2">
            <span className="text-muted-foreground">selling_points（每行一个）</span>
            <textarea
              className="min-h-24 w-full rounded-xl border border-border bg-background px-3 py-2"
              value={scriptDraft.selling_points}
              onChange={(event) =>
                setScriptDraft((draft) => ({ ...draft, selling_points: event.target.value }))
              }
            />
          </label>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">当前状态：{script.status || '未生成'}</p>
      </section>

      <section className="rounded-2xl border border-border bg-card p-5">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-semibold">字幕</h3>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => void run(() => updateOneTakeSubtitle(projectId, subtitleDraft))}
            >
              <Save className="mr-2 h-4 w-4" />
              保存字幕
            </Button>
            <Button
              size="sm"
              onClick={() => {
                if (window.confirm('确认真实生成配音？该操作可能产生费用。')) {
                  void run(() => requestOneTakeVoice(projectId));
                }
              }}
            >
              确认真实配音
            </Button>
            <Button size="sm" onClick={() => void run(() => confirmOneTakeAudioSubtitle(projectId))}>
              确认配音与字幕
            </Button>
          </div>
        </div>
        <div className="mt-4 space-y-2">
          {subtitleDraft.map((segment, index) => (
            <label key={`${segment.index}-${index}`} className="flex gap-3 text-sm">
              <span className="w-10 pt-2 text-right text-muted-foreground">{segment.index}</span>
              <input
                className="w-full rounded-xl border border-border bg-background px-3 py-2"
                value={segment.text}
                onChange={(event) =>
                  setSubtitleDraft((draft) =>
                    draft.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, text: event.target.value } : item,
                    ),
                  )
                }
              />
            </label>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">当前状态：{subtitle.status || '未生成'}</p>
      </section>

      <section className="rounded-2xl border border-border bg-card p-5">
        <div className="flex items-center justify-between gap-3">
          <h3 className="flex items-center gap-2 font-semibold">
            <Video className="h-4 w-4" />
            视频方案
          </h3>
          <div className="flex items-center gap-2">
            <select
              className="rounded-lg border border-border bg-background px-2 py-1 text-sm"
              value={videoMode}
              onChange={(event) => setVideoMode(event.target.value as 'avatar' | 'product')}
            >
              <option value="avatar">有人</option>
              <option value="product">无人</option>
            </select>
            <Button size="sm" onClick={() => void run(() => createOneTakeVideoPlan(projectId, videoMode))}>
              {video.plan_id ? '重新生成方案' : '创建方案'}
            </Button>
          </div>
        </div>
        {video.plan_id ? (
          <div className="mt-3 text-sm text-muted-foreground">
            状态：{video.status || 'unknown'} · 模式：{video.mode || '-'} · 时长：{video.duration_seconds ?? '-'}s
          </div>
        ) : (
          <p className="mt-3 text-sm text-muted-foreground">尚未创建视频方案</p>
        )}
      </section>
    </div>
  );
}