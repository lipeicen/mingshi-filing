import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { ShieldCheck, Search, RefreshCw, Download, FileSpreadsheet, FolderUp, Paperclip, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Card, CardContent } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { api, type PreserveCaseRow, type PreserveCaseDetail, type PreservePreviewCase } from '@/lib/api';
import { fmtAmount } from '@/lib/constants';

const PAGE_SIZE = 15;
const STATUS_OPTS = [{ value: 0, label: '待提交' }, { value: 1, label: '已提交' }];
const STATUS_BADGE: Record<number, 'secondary' | 'default'> = { 0: 'secondary', 1: 'default' };

export default function Preserve() {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [qInput, setQInput] = useState('');
  const [status, setStatus] = useState<number | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ total: number; items: PreserveCaseRow[] }>({ total: 0, items: [] });
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [detail, setDetail] = useState<PreserveCaseDetail | null>(null);
  const [confirmRun, setConfirmRun] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreservePreviewCase[] | null>(null);
  const [previewErrors, setPreviewErrors] = useState<string[]>([]);
  const [importing, setImporting] = useState(false);
  const zipRef = useRef<HTMLInputElement>(null);
  const matRef = useRef<HTMLInputElement>(null);
  const [fileCats, setFileCats] = useState<string[]>([]);
  const [uploadCat, setUploadCat] = useState('');
  const [uploadingMat, setUploadingMat] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api.preserveCases({ status, q, page, size: PAGE_SIZE })
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
      setDetail(await api.preserveCaseDetail(id));
      const c = await api.preserveFileCategories(id);
      setFileCats(c.categories);
      setUploadCat(c.categories[0] ?? '');
    } catch (e) {
      toast.error(`加载详情失败：${(e as Error).message}`);
    }
  };

  // ---- 材料文件：按类别上传 / 删除 / zip 批量 ----
  const uploadMaterials = async (files: FileList | null) => {
    if (!files?.length || !detail) return;
    if (matRef.current) matRef.current.value = '';
    setUploadingMat(true);
    try {
      const r = await api.uploadPreserveFiles(Number(detail.case.id), uploadCat, Array.from(files));
      if (r.rejected.length) {
        toast.warning(`上传完成：${r.saved.length} 个成功，${r.rejected.length} 个被拒绝`,
          { description: r.rejected.map((x) => `${x.name}：${x.reason}`).join('；') });
      } else {
        toast.success(`已上传 ${r.saved.length} 个文件到「${uploadCat}」`);
      }
      await openDetail(Number(detail.case.id));
      load();
    } catch (e) {
      toast.error(`上传失败：${(e as Error).message}`);
    } finally {
      setUploadingMat(false);
    }
  };

  const deleteMaterial = async (fileId: number, name: string) => {
    if (!detail) return;
    try {
      await api.deletePreserveFile(fileId);
      toast.success(`已删除 ${name}`);
      await openDetail(Number(detail.case.id));
      load();
    } catch (e) {
      toast.error(`删除失败：${(e as Error).message}`);
    }
  };

  const pickZip = async (f: File | null) => {
    if (!f) return;
    if (zipRef.current) zipRef.current.value = '';
    try {
      const r = await api.batchPreserveFiles(f);
      toast.success(`批量上传完成：${r.results.length} 个案件，共 ${r.total} 个文件`,
        r.skipped.length ? { description: r.skipped.slice(0, 5).join('；') } : undefined);
      load();
    } catch (e) {
      toast.error(`批量上传失败：${(e as Error).message}`);
    }
  };

  const startRun = async () => {
    setConfirmRun(false);
    try {
      const r = await api.startPreserveRun(selectedPending.map((c) => c.id));
      toast.success(`保全任务已启动：${r.case_nos?.length ?? selectedPending.length} 案（DRY RUN）`);
      setSelected(new Set());
      navigate('/runs');
    } catch (e) {
      toast.error(`启动失败：${(e as Error).message}`);
    }
  };

  // ---- Excel 导入（dry-run 预览 → 确认导入）----
  const pickImport = async (f: File | null) => {
    if (!f) return;
    if (fileRef.current) fileRef.current.value = '';
    try {
      const r = await api.importPreserveCases(f, true);
      setImportFile(f);
      setPreview(r.cases ?? []);
      setPreviewErrors(r.errors ?? []);
      if (!r.cases?.length) toast.error(r.errors?.[0] || '未解析到任何案件');
    } catch (e) {
      toast.error(`解析失败：${(e as Error).message}`);
    }
  };

  const confirmImport = async () => {
    if (!importFile) return;
    setImporting(true);
    try {
      const r = await api.importPreserveCases(importFile);
      const parts = [
        r.created?.length ? `新增 ${r.created.length}` : '',
        r.updated?.length ? `更新 ${r.updated.length}` : '',
        r.failed?.length ? `失败 ${r.failed.length}` : '',
      ].filter(Boolean).join('，');
      if (r.failed?.length || r.errors?.length) {
        toast.warning(`导入完成：${parts}`, { description: [...(r.failed ?? []), ...(r.errors ?? [])].slice(0, 5).join('；') });
      } else {
        toast.success(`导入完成：${parts}`);
      }
      setPreview(null);
      setImportFile(null);
      setPage(1);
      load();
    } catch (e) {
      toast.error(`导入失败：${(e as Error).message}`);
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">保全案件</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">诉讼保全申请管理，数据与立案案件独立</p>
        </div>
        <div className="flex items-center gap-2">
          <input ref={fileRef} type="file" accept=".xlsx,.xls" className="hidden"
                 onChange={(e) => pickImport(e.target.files?.[0] ?? null)} />
          <Button variant="outline" size="sm" asChild>
            <a href={`/api${api.preserveTemplateUrl}`} download="保全案件导入模板.xlsx">
              <Download className="mr-1.5 h-3.5 w-3.5" />下载模板
            </a>
          </Button>
          <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
            <FileSpreadsheet className="mr-1.5 h-3.5 w-3.5" />导入 Excel
          </Button>
          <input ref={zipRef} type="file" accept=".zip" className="hidden"
                 onChange={(e) => pickZip(e.target.files?.[0] ?? null)} />
          <Button variant="outline" size="sm" onClick={() => zipRef.current?.click()}>
            <FolderUp className="mr-1.5 h-3.5 w-3.5" />批量上传材料
          </Button>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />刷新
          </Button>
          <Button size="sm" className="bg-[hsl(6,60%,42%)] text-white hover:bg-[hsl(6,60%,36%)]"
                  disabled={selectedPending.length === 0} onClick={() => setConfirmRun(true)}>
            <ShieldCheck className="mr-1.5 h-4 w-4" />
            发起保全{selectedPending.length > 0 ? `（${selectedPending.length} 案）` : ''}
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <form className="relative w-80" onSubmit={(e) => { e.preventDefault(); setPage(1); setQ(qInput.trim()); }}>
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-8" placeholder="搜索编号 / 案名 / 法院 / 当事人"
                 value={qInput} onChange={(e) => setQInput(e.target.value)} />
        </form>
        <Select value={status === undefined ? 'all' : String(status)}
                onValueChange={(v) => { setPage(1); setStatus(v === 'all' ? undefined : Number(v)); }}>
          <SelectTrigger className="w-36"><SelectValue placeholder="全部状态" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            {STATUS_OPTS.map((s) => <SelectItem key={s.value} value={String(s.value)}>{s.label}</SelectItem>)}
          </SelectContent>
        </Select>
        {selected.size > 0 && (
          <span className="text-sm text-muted-foreground">
            已选 {selected.size} 项（其中待提交 {selectedPending.length} 项）
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
                <TableHead>案件名称</TableHead>
                <TableHead>申请法院</TableHead>
                <TableHead>申请人</TableHead>
                <TableHead>被申请人</TableHead>
                <TableHead className="text-right">保全金额(元)</TableHead>
                <TableHead>财产线索</TableHead>
                <TableHead>材料</TableHead>
                <TableHead>状态</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.length === 0 && (
                <TableRow><TableCell colSpan={10} className="py-10 text-center text-muted-foreground">
                  {loading ? '加载中…' : '暂无保全案件'}
                </TableCell></TableRow>
              )}
              {data.items.map((r) => (
                <TableRow key={r.id} className="cursor-pointer" onClick={() => openDetail(r.id)}>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <Checkbox checked={selected.has(r.id)} onCheckedChange={() => toggleOne(r.id)}
                              aria-label={`选择 ${r.case_no}`} />
                  </TableCell>
                  <TableCell className="tnum font-medium">{r.case_no}</TableCell>
                  <TableCell className="max-w-56 truncate">{r.case_name}</TableCell>
                  <TableCell>{r.court_name}</TableCell>
                  <TableCell>{r.applicant_name}</TableCell>
                  <TableCell>{r.respondent_name}</TableCell>
                  <TableCell className="tnum text-right">{fmtAmount(r.preserve_amount)}</TableCell>
                  <TableCell className="tnum">{r.property_count}</TableCell>
                  <TableCell className="tnum">{r.file_count}</TableCell>
                  <TableCell><Badge variant={STATUS_BADGE[r.status] ?? 'outline'}>{r.status_label}</Badge></TableCell>
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
                  <Badge variant={STATUS_BADGE[detail.case.status as number] ?? 'outline'}>
                    {detail.case.status_label}
                  </Badge>
                </DialogTitle>
              </DialogHeader>
              <div className="space-y-4 text-sm">
                <section>
                  <h3 className="mb-2 font-medium text-muted-foreground">案件信息</h3>
                  <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5">
                    <dt className="text-muted-foreground">案件名称</dt><dd>{String(detail.case.case_name ?? '')}</dd>
                    <dt className="text-muted-foreground">保全类别</dt><dd>{String(detail.case.preserve_category ?? '诉前保全')}</dd>
                    <dt className="text-muted-foreground">保全金额</dt><dd className="tnum">{fmtAmount(Number(detail.case.preserve_amount ?? 0))} 元</dd>
                    <dt className="text-muted-foreground">申请法院</dt><dd>{String(detail.case.court_name ?? '')}</dd>
                    <dt className="text-muted-foreground">担保方式</dt><dd>{String(detail.case.guarantee_type ?? '')}</dd>
                    <dt className="text-muted-foreground">担保价值</dt><dd className="tnum">{fmtAmount(Number(detail.case.guarantee_value ?? 0))} 元</dd>
                  </dl>
                </section>
                <section>
                  <h3 className="mb-2 font-medium text-muted-foreground">当事人</h3>
                  <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5">
                    <dt className="text-muted-foreground">申请人</dt><dd>{String(detail.case.applicant_name ?? '')}</dd>
                    <dt className="text-muted-foreground">被申请人</dt><dd>{String(detail.case.respondent_name ?? '')}</dd>
                  </dl>
                </section>
                {detail.properties.length > 0 && (
                  <section>
                    <h3 className="mb-2 font-medium text-muted-foreground">财产线索（{detail.properties.length}）</h3>
                    <ul className="space-y-1.5">
                      {detail.properties.map((p, i) => (
                        <li key={i} className="flex items-center gap-2 rounded bg-muted px-2.5 py-1.5">
                          <Badge variant="outline">{String(p.property_type ?? '')}</Badge>
                          <span className="tnum">{fmtAmount(Number(p.property_value ?? p.amount ?? 0))} 元</span>
                          <span className="truncate text-muted-foreground">{String(p.bank_name ?? '')} {String(p.description ?? '')}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
                {detail.agents.length > 0 && (
                  <section>
                    <h3 className="mb-2 font-medium text-muted-foreground">代理人（{detail.agents.length}）</h3>
                    <ul className="space-y-1">
                      {detail.agents.map((a, i) => (
                        <li key={i} className="flex items-center gap-2 text-muted-foreground">
                          <Badge variant="outline">{String(a.agent_type ?? '代理人')}</Badge>
                          <span>{String(a.agent_name ?? '')}</span>
                          <span className="tnum">{String(a.agent_phone ?? '')}</span>
                          <span className="truncate">{String(a.agent_law_firm ?? '')}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
                <section>
                  <h3 className="mb-2 font-medium text-muted-foreground">材料文件（{detail.files.length}）</h3>
                  <div className="mb-2 flex items-center gap-2">
                    <Select value={uploadCat} onValueChange={setUploadCat}>
                      <SelectTrigger className="h-8 w-64 text-xs"><SelectValue placeholder="选择材料类别" /></SelectTrigger>
                      <SelectContent>
                        {fileCats.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    <input ref={matRef} type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.doc,.docx"
                           className="hidden" onChange={(e) => uploadMaterials(e.target.files)} />
                    <Button size="sm" variant="outline" className="h-8" disabled={!uploadCat || uploadingMat}
                            onClick={() => matRef.current?.click()}>
                      <Paperclip className="mr-1.5 h-3.5 w-3.5" />{uploadingMat ? '上传中…' : '上传材料'}
                    </Button>
                  </div>
                  {detail.files.length > 0 ? (
                    <ul className="space-y-1">
                      {detail.files.map((f, i) => (
                        <li key={i} className="group flex items-center gap-2 text-muted-foreground">
                          <Badge variant="secondary">{String(f.file_category ?? '')}</Badge>
                          <span className="truncate">{String(f.file_name ?? '')}</span>
                          <button type="button" title="删除"
                                  className="ml-auto hidden text-destructive group-hover:inline"
                                  onClick={() => deleteMaterial(Number(f.id), String(f.file_name ?? ''))}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted-foreground">暂无材料，选择类别后点「上传材料」添加。</p>
                  )}
                </section>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Excel 导入预览 */}
      <Dialog open={!!preview} onOpenChange={(o) => { if (!o) { setPreview(null); setImportFile(null); } }}>
        <DialogContent className="max-h-[85vh] max-w-4xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>保全案件导入预览 — {importFile?.name}</DialogTitle>
          </DialogHeader>
          {preview && (
            <div className="space-y-3 text-sm">
              <p className="text-muted-foreground">
                解析到 {preview.length} 个案件：
                新增 {preview.filter((c) => !c.exists).length} 个，
                更新 {preview.filter((c) => c.exists).length} 个（编号已存在，将覆盖并替换其财产线索/代理人）。
              </p>
              {previewErrors.length > 0 && (
                <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-amber-800">
                  <p className="mb-1 font-medium">以下行存在问题（不会导入）：</p>
                  <ul className="list-inside list-disc space-y-0.5">
                    {previewErrors.map((e, i) => <li key={i}>{e}</li>)}
                  </ul>
                </div>
              )}
              {preview.length > 0 && (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>案件编号</TableHead>
                      <TableHead>案件名称</TableHead>
                      <TableHead>申请法院</TableHead>
                      <TableHead>申请人</TableHead>
                      <TableHead>被申请人</TableHead>
                      <TableHead className="text-right">保全金额(元)</TableHead>
                      <TableHead>财产线索</TableHead>
                      <TableHead>代理人</TableHead>
                      <TableHead>操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {preview.map((c) => (
                      <TableRow key={c.case_no}>
                        <TableCell className="tnum font-medium">{c.case_no}</TableCell>
                        <TableCell className="max-w-40 truncate">{c.case_name}</TableCell>
                        <TableCell>{c.court_name}</TableCell>
                        <TableCell>{c.applicant_name}</TableCell>
                        <TableCell>{c.respondent_name}</TableCell>
                        <TableCell className="tnum text-right">{fmtAmount(c.preserve_amount)}</TableCell>
                        <TableCell className="tnum">{c.properties}</TableCell>
                        <TableCell className="tnum">{c.agents}</TableCell>
                        <TableCell>
                          <Badge variant={c.exists ? 'secondary' : 'default'}>{c.exists ? '更新' : '新增'}</Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" size="sm" onClick={() => { setPreview(null); setImportFile(null); }}>取消</Button>
                <Button size="sm" disabled={importing || preview.length === 0} onClick={confirmImport}
                        className="bg-[hsl(6,60%,42%)] text-white hover:bg-[hsl(6,60%,36%)]">
                  {importing ? '导入中…' : `确认导入（${preview.length} 案）`}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* 发起保全确认 */}
      <AlertDialog open={confirmRun} onOpenChange={setConfirmRun}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认发起保全申请？</AlertDialogTitle>
            <AlertDialogDescription>
              将对 {selectedPending.length} 个待提交案件执行自动化保全申请流程（DRY RUN 模式，不实际提交）。
              每案约 3～5 分钟，期间请勿操作弹出的浏览器窗口。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={startRun}>开始执行</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
