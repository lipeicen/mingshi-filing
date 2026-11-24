import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Square, RefreshCw, Terminal, Loader2, Clock } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { api, type RunMeta, type RunCaseResult } from '@/lib/api';
import { RUN_STATUS_META, fmtAmount } from '@/lib/constants';

const fmtDuration = (s: number) => (s >= 60 ? `${Math.floor(s / 60)}分${s % 60}秒` : `${s}秒`);

/** 报告状态 → 展示。DRY RUN 的「待提交」即预览通过（成功） */
function caseBadge(c: RunCaseResult) {
  const ok = c.status === '待提交' || c.status === '已提交' || c.status === '成功';
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant={ok ? 'secondary' : 'destructive'} className="cursor-default">
            {ok ? '预览通过' : c.status || '失败'}
          </Badge>
        </TooltipTrigger>
        <TooltipContent>{c.message || c.status}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default function Runs() {
  const [runs, setRuns] = useState<RunMeta[]>([]);
  const [active, setActive] = useState<RunMeta | null>(null);
  const [detail, setDetail] = useState<RunMeta | null>(null);
  const [log, setLog] = useState('');
  const [confirmCancel, setConfirmCancel] = useState(false);
  const offsetRef = useRef(0);
  const logRef = useRef<HTMLPreElement>(null);

  const loadRuns = useCallback(() => {
    api.runs().then((r) => {
      setRuns(r.items);
      setActive((cur) => {
        if (cur) {
          const found = r.items.find((x) => x.id === cur.id);
          return found ?? cur;
        }
        return r.items[0] ?? null;
      });
    }).catch((e) => toast.error(`加载运行记录失败：${e.message}`));
  }, []);

  useEffect(() => {
    loadRuns();
    const t = setInterval(loadRuns, 5000);
    return () => clearInterval(t);
  }, [loadRuns]);

  // 选中运行：轮询逐案结果 + 增量拉日志
  useEffect(() => {
    if (!active) return;
    offsetRef.current = 0;
    setLog('');
    setDetail(null);
    let stop = false;
    const pullDetail = () => {
      api.run(active.id).then((d) => { if (!stop) setDetail(d); }).catch(() => { /* 下轮再试 */ });
    };
    const pullLog = () => {
      api.runLog(active.id, offsetRef.current).then((r) => {
        if (stop) return;
        offsetRef.current = r.offset;
        if (r.text) setLog((prev) => prev + r.text);
      }).catch(() => { /* 下轮再试 */ });
    };
    pullDetail();
    pullLog();
    const t = setInterval(() => { pullDetail(); pullLog(); }, 2000);
    return () => { stop = true; clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.id]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [log]);

  const doCancel = async () => {
    setConfirmCancel(false);
    if (!active) return;
    try {
      await api.cancelRun(active.id);
      toast.success('已终止该运行');
      loadRuns();
    } catch (e) {
      toast.error(`终止失败：${(e as Error).message}`);
    }
  };

  const doneNos = new Set((detail?.cases ?? []).map((c) => c.case_no));
  const pendingNos = (active?.case_nos ?? []).filter(
    (n) => !doneNos.has(n) && n !== detail?.current_case,
  );
  const doneOk = (detail?.cases ?? []).filter(
    (c) => c.status === '待提交' || c.status === '已提交' || c.status === '成功',
  ).length;

  return (
    <div className="flex h-[calc(100dvh-3rem)] flex-col space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">立案运行</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={loadRuns}>
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" />刷新
          </Button>
          {active?.status === 'running' && (
            <Button variant="destructive" size="sm" onClick={() => setConfirmCancel(true)}>
              <Square className="mr-1.5 h-3.5 w-3.5" />终止运行
            </Button>
          )}
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-4 gap-4">
        <Card className="col-span-1 overflow-y-auto">
          <CardHeader><CardTitle className="text-base">运行记录</CardTitle></CardHeader>
          <CardContent className="p-0">
            {runs.length === 0 && (
              <p className="px-6 pb-6 text-sm text-muted-foreground">暂无运行记录</p>
            )}
            <ul className="divide-y">
              {runs.map((r) => {
                const m = RUN_STATUS_META[r.status];
                return (
                  <li key={r.id}>
                    <button
                      type="button"
                      onClick={() => setActive(r)}
                      className={`w-full px-4 py-3 text-left text-sm transition-colors outline-none
                        focus-visible:ring-2 focus-visible:ring-ring
                        ${active?.id === r.id ? 'bg-primary/5 border-l-2 border-l-primary' : 'hover:bg-muted/50'}`}
                    >
                      <div className="flex items-center justify-between">
                        <Badge variant={m.variant}>{m.label}</Badge>
                        <span className="text-xs text-muted-foreground">{r.case_nos.length} 案</span>
                      </div>
                      <div className="tnum mt-1 text-xs text-muted-foreground">{r.started_at}</div>
                      <div className="mt-1 truncate text-xs">{r.case_nos.join('、')}</div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>

        <div className="col-span-3 flex min-h-0 flex-col gap-4">
          {/* 逐案结果 */}
          <Card className="shrink-0">
            <CardHeader className="flex-row items-center gap-3 py-3">
              <CardTitle className="text-base">逐案结果</CardTitle>
              {active && (
                <>
                  <Badge variant={RUN_STATUS_META[active.status].variant}>{RUN_STATUS_META[active.status].label}</Badge>
                  <span className="tnum text-sm text-muted-foreground">
                    {doneOk} 通过 / {(detail?.cases ?? []).length} 已完成 / 共 {active.case_nos.length} 案
                  </span>
                </>
              )}
            </CardHeader>
            <CardContent className="p-0">
              {!active ? (
                <p className="px-6 pb-4 text-sm text-muted-foreground">选择左侧运行记录查看结果</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>案件编号</TableHead>
                      <TableHead>受理法院</TableHead>
                      <TableHead>案由</TableHead>
                      <TableHead className="text-right">标的金额(元)</TableHead>
                      <TableHead>当事人/材料</TableHead>
                      <TableHead>耗时</TableHead>
                      <TableHead>结果</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(detail?.cases ?? []).map((c) => (
                      <TableRow key={c.case_no}>
                        <TableCell className="tnum font-medium">{c.case_no}</TableCell>
                        <TableCell>{c.court_name}</TableCell>
                        <TableCell>{c.case_cause}</TableCell>
                        <TableCell className="tnum text-right">{fmtAmount(Number(c.amount ?? 0))}</TableCell>
                        <TableCell className="tnum">{c.parties_count} / {c.documents_count}</TableCell>
                        <TableCell className="tnum">{fmtDuration(c.duration_seconds ?? 0)}</TableCell>
                        <TableCell>{caseBadge(c)}</TableCell>
                      </TableRow>
                    ))}
                    {detail?.current_case && active.status === 'running' && (
                      <TableRow className="bg-primary/5">
                        <TableCell className="tnum font-medium">{detail.current_case}</TableCell>
                        <TableCell colSpan={4} className="text-muted-foreground">浏览器自动化执行中…</TableCell>
                        <TableCell><Clock className="h-3.5 w-3.5 animate-pulse" /></TableCell>
                        <TableCell>
                          <Badge variant="default" className="gap-1">
                            <Loader2 className="h-3 w-3 animate-spin" />进行中
                          </Badge>
                        </TableCell>
                      </TableRow>
                    )}
                    {detail?.current_case && active.status !== 'running' && (
                      <TableRow className="text-muted-foreground">
                        <TableCell className="tnum font-medium">{detail.current_case}</TableCell>
                        <TableCell colSpan={5}>运行结束时仍在处理，未完成</TableCell>
                        <TableCell><Badge variant="outline">未完成</Badge></TableCell>
                      </TableRow>
                    )}
                    {pendingNos.map((n) => (
                      <TableRow key={n} className="text-muted-foreground">
                        <TableCell className="tnum">{n}</TableCell>
                        <TableCell colSpan={5}>排队等待</TableCell>
                        <TableCell><Badge variant="outline">待执行</Badge></TableCell>
                      </TableRow>
                    ))}
                    {detail && !detail.cases?.length && !detail.current_case && active.status !== 'running' && (
                      <TableRow><TableCell colSpan={7} className="py-6 text-center text-muted-foreground">
                        本次运行没有产生逐案结果（可能被提前终止）
                      </TableCell></TableRow>
                    )}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* 原始日志 */}
          <Card className="flex min-h-0 flex-1 flex-col">
            <CardHeader className="flex-row items-center gap-2 py-3">
              <Terminal className="h-4 w-4" />
              <CardTitle className="text-base">原始日志</CardTitle>
            </CardHeader>
            <CardContent className="min-h-0 flex-1">
              {active ? (
                <pre ref={logRef}
                     className="h-full overflow-auto rounded-md bg-[hsl(224,42%,12%)] p-4 font-mono text-xs leading-relaxed text-[hsl(220,20%,85%)]">
                  {log || '（等待日志输出…）'}
                </pre>
              ) : (
                <p className="text-sm text-muted-foreground">选择左侧运行记录查看日志</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <AlertDialog open={confirmCancel} onOpenChange={setConfirmCancel}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认终止当前立案运行？</AlertDialogTitle>
            <AlertDialogDescription>
              将强制结束立案进程及其浏览器，正在处理的案件可能停留在中间状态（DRY RUN 不会真实提交）。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={doCancel}>终止运行</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
