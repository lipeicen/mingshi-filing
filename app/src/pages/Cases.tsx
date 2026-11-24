import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { PlayCircle, Search, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Card, CardContent } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { api, type CaseRow, type CaseDetail } from '@/lib/api';
import { CASE_STATUS, CASE_STATUS_BADGE, fmtAmount } from '@/lib/constants';

const PAGE_SIZE = 15;

export default function Cases() {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [qInput, setQInput] = useState('');
  const [status, setStatus] = useState<number | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ total: number; items: CaseRow[] }>({ total: 0, items: [] });
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [confirmRun, setConfirmRun] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api.cases({ status, q, page, size: PAGE_SIZE })
      .then((r) => setData({ total: r.total, items: r.items }))
      .catch((e) => toast.error(`加载失败：${e.message}`))
      .finally(() => setLoading(false));
  }, [status, q, page]);

  useEffect(() => { load(); }, [load]);

  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const allChecked = data.items.length > 0 && data.items.every((r) => selected.has(r.id));
  const selectedPending = useMemo(
    () => data.items.filter((r) => selected.has(r.id) && r.status === 0),
    [data.items, selected],
  );

  const toggleAll = () => {
    const next = new Set(selected);
    if (allChecked) data.items.forEach((r) => next.delete(r.id));
    else data.items.forEach((r) => next.add(r.id));
    setSelected(next);
  };
  const toggleOne = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelected(next);
  };

  const openDetail = async (id: number) => {
    try {
      setDetail(await api.caseDetail(id));
    } catch (e) {
      toast.error(`加载详情失败：${(e as Error).message}`);
    }
  };

  const startRun = async () => {
    setConfirmRun(false);
    try {
      const r = await api.startRun(selectedPending.map((c) => c.id));
      toast.success(`立案任务已启动：${r.case_nos?.length ?? selectedPending.length} 案（DRY RUN）`);
      setSelected(new Set());
      navigate('/runs');
    } catch (e) {
      toast.error(`启动失败：${(e as Error).message}`);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">案件管理</h1>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />刷新
          </Button>
          <Button size="sm" className="bg-[hsl(6,60%,42%)] text-white hover:bg-[hsl(6,60%,36%)]"
                  disabled={selectedPending.length === 0} onClick={() => setConfirmRun(true)}>
            <PlayCircle className="mr-1.5 h-4 w-4" />
            立案{selectedPending.length > 0 ? `（${selectedPending.length} 案）` : ''}
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <form className="relative w-80" onSubmit={(e) => { e.preventDefault(); setPage(1); setQ(qInput.trim()); }}>
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-8" placeholder="搜索编号 / 法院 / 当事人 / 案由"
                 value={qInput} onChange={(e) => setQInput(e.target.value)} />
        </form>
        <Select value={status === undefined ? 'all' : String(status)}
                onValueChange={(v) => { setPage(1); setStatus(v === 'all' ? undefined : Number(v)); }}>
          <SelectTrigger className="w-36"><SelectValue placeholder="全部状态" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            {CASE_STATUS.map((s) => <SelectItem key={s.value} value={String(s.value)}>{s.label}</SelectItem>)}
          </SelectContent>
        </Select>
        {selected.size > 0 && (
          <span className="text-sm text-muted-foreground">
            已选 {selected.size} 项（其中待立案 {selectedPending.length} 项）
          </span>
        )}
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <Checkbox checked={allChecked} onCheckedChange={toggleAll} aria-label="全选" />
                </TableHead>
                <TableHead>案件编号</TableHead>
                <TableHead>受理法院</TableHead>
                <TableHead>案由</TableHead>
                <TableHead>原告</TableHead>
                <TableHead>被告</TableHead>
                <TableHead className="text-right">标的金额(元)</TableHead>
                <TableHead>状态</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.length === 0 && (
                <TableRow><TableCell colSpan={8} className="py-10 text-center text-muted-foreground">
                  {loading ? '加载中…' : '暂无数据，去「数据上传」导入案件 JSON'}
                </TableCell></TableRow>
              )}
              {data.items.map((r) => (
                <TableRow key={r.id} className="cursor-pointer" onClick={() => openDetail(r.id)}>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <Checkbox checked={selected.has(r.id)} onCheckedChange={() => toggleOne(r.id)}
                              aria-label={`选择 ${r.case_no}`} />
                  </TableCell>
                  <TableCell className="tnum font-medium">{r.case_no}</TableCell>
                  <TableCell>{r.court_name}</TableCell>
                  <TableCell>{r.case_reason}</TableCell>
                  <TableCell>{r.applicant_name}{r.applicant_nature !== '自然人' && <Badge variant="outline" className="ml-1">法人</Badge>}</TableCell>
                  <TableCell>{r.respondent_name}</TableCell>
                  <TableCell className="tnum text-right">{fmtAmount(r.claim_amount)}</TableCell>
                  <TableCell><Badge variant={CASE_STATUS_BADGE[r.status] ?? 'outline'}>{r.status_label}</Badge></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span className="tnum">共 {data.total} 条，第 {page} / {pages} 页</span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button>
          <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>下一页</Button>
        </div>
      </div>

      {/* 详情弹窗 */}
      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
          {detail && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  {String(detail.case.case_no)}
                  <Badge variant={CASE_STATUS_BADGE[detail.case.status as number] ?? 'outline'}>
                    {detail.case.status_label}
                  </Badge>
                </DialogTitle>
              </DialogHeader>
              <div className="space-y-4 text-sm">
                <section>
                  <h3 className="mb-2 font-medium text-muted-foreground">案件信息</h3>
                  <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5">
                    <dt className="text-muted-foreground">受理法院</dt><dd>{String(detail.case.court_name)}（{String(detail.case.court_province)}）</dd>
                    <dt className="text-muted-foreground">案由</dt><dd>{String(detail.case.case_reason)}</dd>
                    <dt className="text-muted-foreground">标的金额</dt><dd className="tnum">{fmtAmount(Number(detail.case.claim_amount))} 元</dd>
                    <dt className="text-muted-foreground">案件类型</dt><dd>{String(detail.case.case_type)}</dd>
                  </dl>
                  {!!detail.case.claim && <p className="mt-2 rounded bg-muted p-2.5 leading-relaxed"><b>诉讼请求：</b>{String(detail.case.claim)}</p>}
                  {!!detail.case.facts && <p className="mt-2 rounded bg-muted p-2.5 leading-relaxed"><b>事实与理由：</b>{String(detail.case.facts)}</p>}
                </section>
                <section>
                  <h3 className="mb-2 font-medium text-muted-foreground">当事人</h3>
                  <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5">
                    <dt className="text-muted-foreground">原告（{String(detail.case.applicant_nature)}）</dt><dd>{String(detail.case.applicant_name)}</dd>
                    <dt className="text-muted-foreground">被告（{String(detail.case.respondent_nature)}）</dt><dd>{String(detail.case.respondent_name)}</dd>
                  </dl>
                </section>
                <section>
                  <h3 className="mb-2 font-medium text-muted-foreground">代理人（{detail.agents.length}）</h3>
                  {detail.agents.length === 0 ? <p className="text-muted-foreground">无</p> : (
                    <ul className="space-y-1">
                      {detail.agents.map((a) => (
                        <li key={String(a.id)}>{String(a.agent_name)} · {String(a.agent_type)} · {String(a.agent_law_firm ?? '')}</li>
                      ))}
                    </ul>
                  )}
                </section>
                <section>
                  <h3 className="mb-2 font-medium text-muted-foreground">诉讼材料（{detail.files.length}）</h3>
                  <ul className="space-y-1">
                    {detail.files.map((f) => (
                      <li key={String(f.id)} className="flex justify-between">
                        <span>{String(f.file_name)}</span>
                        <Badge variant="outline">{String(f.file_category)}</Badge>
                      </li>
                    ))}
                  </ul>
                </section>
                <section className="flex items-center gap-2 border-t pt-3">
                  <span className="text-muted-foreground">修改状态：</span>
                  {CASE_STATUS.map((s) => (
                    <Button key={s.value} variant="outline" size="sm"
                            disabled={detail.case.status === s.value}
                            onClick={async () => {
                              try {
                                await api.updateStatus(detail.case.id as number, s.value);
                                toast.success(`已改为「${s.label}」`);
                                setDetail(null);
                                load();
                              } catch (e) { toast.error((e as Error).message); }
                            }}>
                      {s.label}
                    </Button>
                  ))}
                </section>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* 立案确认 */}
      <AlertDialog open={confirmRun} onOpenChange={setConfirmRun}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认发起立案？</AlertDialogTitle>
            <AlertDialogDescription>
              将对 {selectedPending.length} 个待立案案件执行自动立案流程（DRY RUN 模式：走到预览页，不真实提交）：
              <span className="mt-2 block max-h-32 overflow-y-auto tnum">
                {selectedPending.map((c) => c.case_no).join('、')}
              </span>
              每案约需 4 分钟，期间可在「立案运行」查看实时日志。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={startRun}>开始立案</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
