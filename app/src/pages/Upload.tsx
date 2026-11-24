import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { UploadCloud, FileJson, FileSpreadsheet, AlertCircle, CheckCircle2, Download, FolderUp, X, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { api, DOC_CATEGORIES, categoryFromPath, type ImportResult, type PreviewCase, type FilesUploadResult, type UploadedFile } from '@/lib/api';
import { fmtAmount } from '@/lib/constants';

const ACCEPT_DATA = '.json,.xlsx,application/json,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
const ACCEPT_FILES = '.pdf,.png,.jpg,.jpeg';

const fmtSize = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.ceil(n / 1024)} KB`);

export default function Upload() {
  const inputRef = useRef<HTMLInputElement>(null);
  const filesInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewCase[] | null>(null);
  const [parseErr, setParseErr] = useState<string[]>([]);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  // 材料批量上传
  const [matFiles, setMatFiles] = useState<{ file: File; category: string }[]>([]);
  const [matResult, setMatResult] = useState<FilesUploadResult | null>(null);
  const [matBusy, setMatBusy] = useState(false);
  const [uploaded, setUploaded] = useState<UploadedFile[]>([]);
  const [fileQuery, setFileQuery] = useState('');
  const [fileCat, setFileCat] = useState('all');
  const [fileCase, setFileCase] = useState('all');

  // 从文件名提取案件编号前缀（TEST-2026-UI-101_起诉状.pdf → TEST-2026-UI-101）
  const casePrefixOf = (name: string) => {
    const m = name.match(/^([A-Za-z0-9-]+)_/);
    return m ? m[1] : '';
  };
  const caseOptions = [...new Set(uploaded.map((u) => casePrefixOf(u.name)).filter(Boolean))].sort();
  const filteredUploaded = uploaded.filter((u) => {
    if (fileCase !== 'all' && casePrefixOf(u.name) !== fileCase) return false;
    if (fileCat !== 'all' && u.category !== fileCat) return false;
    if (fileQuery && !u.name.toLowerCase().includes(fileQuery.toLowerCase())) return false;
    return true;
  });

  const loadUploaded = () => {
    api.listFiles().then((r) => setUploaded(r.items)).catch(() => { /* 忽略 */ });
  };
  useEffect(loadUploaded, []);

  const resetData = () => {
    setResult(null);
    setParseErr([]);
    setPreview(null);
  };

  const pickFile = async (f: File | undefined | null) => {
    resetData();
    if (!f) return;
    const isXlsx = /\.xlsx?$/i.test(f.name);
    const isJson = /\.json$/i.test(f.name);
    if (!isXlsx && !isJson) {
      setParseErr(['仅支持 .json 或 .xlsx 文件']);
      return;
    }
    setFile(f);
    if (isJson) {
      // JSON 本地解析预览
      try {
        const data = JSON.parse(await f.text());
        if (!Array.isArray(data) || data.length === 0) {
          setParseErr(['JSON 须为非空案件数组']);
          return;
        }
        setPreview(data);
      } catch (e) {
        setParseErr([`JSON 解析失败：${(e as Error).message}`]);
      }
    } else {
      // Excel 走服务端解析预览（dry run）
      setBusy(true);
      try {
        const r = await api.importCases(f, true);
        if (r.ok && r.cases) {
          setPreview(r.cases);
        } else {
          setParseErr(r.errors?.length ? r.errors : ['Excel 解析未通过']);
          if (r.cases?.length) setPreview(r.cases);
        }
      } catch (e) {
        setParseErr([`Excel 解析失败：${(e as Error).message}`]);
      } finally {
        setBusy(false);
      }
    }
  };

  const doImport = async () => {
    if (!file) return;
    setBusy(true);
    setResult(null);
    try {
      const r = await api.importCases(file);
      setResult(r);
      if (r.ok) toast.success(`导入完成：新增 ${r.imported?.length ?? 0} 案`);
      else toast.error('导入校验未通过');
    } catch (e) {
      toast.error(`导入失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const addMatFiles = (list: FileList | null) => {
    if (!list) return;
    setMatResult(null);
    const incoming = Array.from(list);
    setMatFiles((prev) => {
      const names = new Set(prev.map((x) => x.file.name));
      return [
        ...prev,
        ...incoming
          .filter((f) => !names.has(f.name))
          .map((f) => ({ file: f, category: categoryFromPath(f) })),
      ];
    });
  };

  const doUploadFiles = async () => {
    if (!matFiles.length) return;
    setMatBusy(true);
    try {
      const r = await api.uploadFiles(matFiles);
      setMatResult(r);
      if (r.ok) {
        toast.success(`已上传 ${r.saved.length} 个材料文件`);
        setMatFiles([]);
      } else {
        toast.warning(`上传 ${r.saved.length} 个，拒绝 ${r.rejected.length} 个`);
      }
      loadUploaded();
    } catch (e) {
      toast.error(`上传失败：${(e as Error).message}`);
    } finally {
      setMatBusy(false);
    }
  };

  const doDeleteFile = async (name: string) => {
    try {
      await api.deleteFile(name);
      toast.success(`已删除 ${name}`);
      loadUploaded();
    } catch (e) {
      toast.error(`删除失败：${(e as Error).message}`);
    }
  };

  const isXlsx = !!file && /\.xlsx?$/i.test(file.name);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">数据上传</h1>
        <Button variant="outline" size="sm" asChild>
          <a href={`/api${api.templateUrl}`} download="案件导入模板.xlsx">
            <Download className="mr-1.5 h-3.5 w-3.5" />下载 Excel 模板
          </a>
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        支持 <b>Excel（.xlsx）</b>或 JSON 案件数据：服务端校验必填字段与身份证校验位后写入 MySQL（按案件编号幂等，重复导入自动更新）。
        Excel 的「材料文件」列填文件名（分号分隔），需先在下方批量上传对应材料；留空则使用默认六份材料。
      </p>

      {/* ===== 材料文件批量上传 ===== */}
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <FolderUp className="h-4 w-4" />材料文件批量上传
            <span className="text-xs font-normal text-muted-foreground">pdf / png / jpg ≤ 20MB；整文件夹上传时按类别子文件夹自动归类</span>
          </CardTitle>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" asChild>
              <a href={`/api${api.folderTemplateUrl}`} download="材料文件夹模板.zip">
                <Download className="mr-1.5 h-3.5 w-3.5" />文件夹模板
              </a>
            </Button>
            <Button variant="outline" size="sm" onClick={() => filesInputRef.current?.click()}>
              选择文件
            </Button>
            <Button variant="outline" size="sm" onClick={() => folderInputRef.current?.click()}>
              选择文件夹
            </Button>
            <Button size="sm" disabled={!matFiles.length || matBusy} onClick={doUploadFiles}
                    className="bg-primary text-primary-foreground hover:bg-primary/90">
              {matBusy ? '上传中…' : `上传${matFiles.length ? `（${matFiles.length}）` : ''}`}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <input ref={filesInputRef} type="file" multiple accept={ACCEPT_FILES} className="hidden"
                 onChange={(e) => { addMatFiles(e.target.files); e.target.value = ''; }} />
          <input ref={(el) => { folderInputRef.current = el; el?.setAttribute('webkitdirectory', ''); }}
                 type="file" multiple className="hidden"
                 onChange={(e) => { addMatFiles(e.target.files); e.target.value = ''; }} />
          {matFiles.length > 0 && (
            <ul className="divide-y rounded-md border">
              {matFiles.map((x) => (
                <li key={x.file.name} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <span className="min-w-0 flex-1 truncate">{x.file.name}</span>
                  <span className="tnum text-xs text-muted-foreground">{fmtSize(x.file.size)}</span>
                  <Select value={x.category}
                          onValueChange={(v) =>
                            setMatFiles((prev) =>
                              prev.map((p) => (p.file.name === x.file.name ? { ...p, category: v } : p)),
                            )
                          }>
                    <SelectTrigger className="h-8 w-36" aria-label={`${x.file.name} 材料类别`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {DOC_CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <button type="button" aria-label={`移除 ${x.file.name}`}
                          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => setMatFiles((prev) => prev.filter((p) => p.file.name !== x.file.name))}>
                    <X className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {matFiles.length === 0 && !matResult && uploaded.length === 0 && (
            <p className="text-sm text-muted-foreground">
              选择单个/多个文件，或「选择文件夹」整包上传——按类别子文件夹（起诉状/身份证明/证据…）自动归类，可下载「文件夹模板」。
            </p>
          )}
          {uploaded.length > 0 && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-xs font-medium text-muted-foreground">
                  已上传材料（{filteredUploaded.length}/{uploaded.length}）：
                </p>
                <div className="flex-1" />
                {caseOptions.length > 0 && (
                  <Select value={fileCase} onValueChange={setFileCase}>
                    <SelectTrigger className="h-8 w-44" aria-label="按案件筛选">
                      <SelectValue placeholder="全部案件" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">全部案件</SelectItem>
                      {caseOptions.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                    </SelectContent>
                  </Select>
                )}
                <Select value={fileCat} onValueChange={setFileCat}>
                  <SelectTrigger className="h-8 w-36" aria-label="按类别筛选">
                    <SelectValue placeholder="全部类别" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部类别</SelectItem>
                    {DOC_CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                  </SelectContent>
                </Select>
                <input
                  type="search"
                  value={fileQuery}
                  onChange={(e) => setFileQuery(e.target.value)}
                  placeholder="搜索文件名…"
                  aria-label="搜索文件名"
                  className="h-8 w-40 rounded-md border border-input bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </div>
              <ul className="max-h-72 divide-y overflow-y-auto rounded-md border">
                {filteredUploaded.map((u) => (
                  <li key={u.name} className="flex items-center gap-3 px-3 py-1.5 text-sm">
                    <span className="min-w-0 flex-1 truncate">{u.name}</span>
                    <Badge variant="secondary">{u.category}</Badge>
                    <span className="tnum text-xs text-muted-foreground">{fmtSize(u.size)}</span>
                    <button type="button" aria-label={`删除 ${u.name}`}
                            className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            onClick={() => doDeleteFile(u.name)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
                {filteredUploaded.length === 0 && (
                  <li className="px-3 py-4 text-center text-sm text-muted-foreground">没有匹配的材料</li>
                )}
              </ul>
            </div>
          )}
          {matResult && (
            <div className="space-y-1.5 text-sm">
              {matResult.saved.map((s) => (
                <p key={s.path} className="flex items-center gap-1.5 text-[hsl(150,60%,32%)]">
                  <CheckCircle2 className="h-4 w-4 shrink-0" />
                  {s.name} <Badge variant="secondary">{s.category}</Badge>
                  <span className="tnum text-xs text-muted-foreground">→ {s.path}</span>
                </p>
              ))}
              {matResult.rejected.map((r) => (
                <p key={r.name} className="flex items-center gap-1.5 text-destructive">
                  <AlertCircle className="h-4 w-4 shrink-0" />{r.name}：{r.reason}
                </p>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ===== 案件数据上传 ===== */}
      <Card>
        <CardContent className="p-6">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); pickFile(e.dataTransfer.files?.[0]); }}
            className={`flex w-full flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed py-12 transition-colors
              outline-none focus-visible:ring-2 focus-visible:ring-ring
              ${dragOver ? 'border-primary bg-primary/5' : 'border-input hover:border-primary/60 hover:bg-muted/40'}`}
          >
            <UploadCloud className="h-10 w-10 text-muted-foreground" />
            <span className="text-sm font-medium">点击选择或拖拽 Excel / JSON 案件数据到此处</span>
            <span className="text-xs text-muted-foreground">Excel 请使用「下载 Excel 模板」的列格式</span>
          </button>
          <input ref={inputRef} type="file" accept={ACCEPT_DATA} className="hidden"
                 onChange={(e) => pickFile(e.target.files?.[0])} />
          {parseErr.length > 0 && (
            <div className="mt-3 space-y-1">
              {parseErr.map((e, i) => (
                <p key={i} className="flex items-center gap-1.5 text-sm text-destructive">
                  <AlertCircle className="h-4 w-4 shrink-0" />{e}
                </p>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {preview && (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              {isXlsx ? <FileSpreadsheet className="h-4 w-4" /> : <FileJson className="h-4 w-4" />}
              {file?.name} — 解析到 {preview.length} 个案件
              {isXlsx && <Badge variant="secondary">服务端解析</Badge>}
            </CardTitle>
            <Button onClick={doImport} disabled={busy || parseErr.length > 0}
                    className="bg-[hsl(6,60%,42%)] text-white hover:bg-[hsl(6,60%,36%)]">
              {busy ? '处理中…' : '确认导入数据库'}
            </Button>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>案件编号</TableHead>
                  <TableHead>省份</TableHead>
                  <TableHead>受理法院</TableHead>
                  <TableHead>案由</TableHead>
                  <TableHead>原告 / 被告</TableHead>
                  <TableHead className="text-right">标的金额(元)</TableHead>
                  <TableHead>材料 / 代理人</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {preview.map((c, i) => (
                  <TableRow key={c.case_no ?? i}>
                    <TableCell className="tnum font-medium">{c.case_no ?? <Badge variant="destructive">缺编号</Badge>}</TableCell>
                    <TableCell>{c.court_province ?? '北京'}</TableCell>
                    <TableCell>{c.court_name}</TableCell>
                    <TableCell>{c.case_cause}</TableCell>
                    <TableCell>{c.plaintiff?.name} / {c.defendant?.name}</TableCell>
                    <TableCell className="tnum text-right">{fmtAmount(Number(c.amount ?? 0))}</TableCell>
                    <TableCell className="tnum">{c.documents?.length ?? 0} / {c.agents?.length ?? 0}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {result && (
        <Card className={result.ok ? 'border-[hsl(150,60%,38%)]' : 'border-destructive'}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              {result.ok
                ? <><CheckCircle2 className="h-5 w-5 text-[hsl(150,60%,38%)]" />导入成功</>
                : <><AlertCircle className="h-5 w-5 text-destructive" />导入未通过校验</>}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {result.errors?.map((e, i) => (
              <p key={i} className="text-destructive">· {e}</p>
            ))}
            {!!result.imported?.length && (
              <p>新增：{result.imported.map((r) => `${r.case_no}(id=${r.id})`).join('、')}</p>
            )}
            {!!result.updated?.length && <p>更新：{result.updated.join('、')}</p>}
            {result.saved_as && <p className="text-muted-foreground">已存档：test_data/uploads/{result.saved_as}</p>}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
