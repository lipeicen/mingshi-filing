const API_BASE = '/api';

export interface CaseRow {
  id: number;
  case_no: string;
  case_type: string;
  court_name: string;
  court_province: string;
  case_reason: string;
  claim_amount: number;
  applicant_name: string;
  applicant_nature: string;
  respondent_name: string;
  status: number;
  status_label: string;
  created_at: string;
}

export interface Stats {
  total: number;
  by_status: Record<string, number>;
  agents: number;
  files: number;
  provinces: number;
  by_province: { province: string; count: number }[];
}

export interface CaseListResp {
  total: number;
  page: number;
  size: number;
  items: CaseRow[];
}

export interface CaseDetail {
  case: Record<string, unknown> & { status_label: string };
  agents: Record<string, unknown>[];
  files: Record<string, unknown>[];
}

export interface ImportResult {
  ok: boolean;
  dry?: boolean;
  errors?: string[];
  cases?: PreviewCase[] | null;
  saved_as?: string;
  imported?: { case_no: string; id: number }[];
  updated?: string[];
  log?: string;
}

export interface PreviewCase {
  case_no?: string;
  court_name?: string;
  court_province?: string;
  case_cause?: string;
  amount?: number;
  plaintiff?: { name?: string };
  defendant?: { name?: string };
  agents?: unknown[];
  documents?: unknown[];
}

export interface FilesUploadResult {
  ok: boolean;
  saved: { name: string; path: string; size: number; category: string }[];
  rejected: { name: string; reason: string }[];
}

export interface UploadedFile {
  name: string;
  path: string;
  size: number;
  category: string;
}

export const DOC_CATEGORIES = ['起诉状', '身份证明', '证据', '委托书', '送达地址确认书', '其他'];

/** 按文件名关键词推断默认类别（与服务端一致） */
export function inferCategory(filename: string): string {
  const low = filename.toLowerCase();
  const rules: [string, string][] = [
    ['起诉状', '起诉状'], ['complaint', '起诉状'],
    ['身份证明', '身份证明'], ['身份证', '身份证明'],
    ['证据', '证据'], ['evidence', '证据'],
    ['委托', '委托书'], ['authorization', '委托书'],
    ['送达', '送达地址确认书'], ['service', '送达地址确认书'],
    ['_id', '身份证明'],
  ];
  for (const [kw, t] of rules) if (low.includes(kw) || filename.includes(kw)) return t;
  return '证据';
}

/** 文件夹上传：类别优先取文件所在的类别子文件夹名，其次按文件名推断 */
export function categoryFromPath(file: File): string {
  const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath || '';
  const dirs = rel.split('/').slice(0, -1);
  for (const d of dirs) {
    if (DOC_CATEGORIES.includes(d)) return d;
  }
  return inferCategory(file.name);
}

export interface RunCaseResult {
  case_no: string;
  status: string;
  message: string;
  court_name: string;
  case_cause: string;
  amount: number;
  parties_count: number;
  documents_count: number;
  duration_seconds: number;
  submitted_at: string;
}

export interface RunMeta {
  id: string;
  case_nos: string[];
  started_at: string;
  finished_at: string | null;
  status: 'running' | 'success' | 'failed' | 'cancelled' | 'interrupted';
  returncode: number | null;
  results?: string[];
  cases?: RunCaseResult[];
  current_case?: string | null;
  total_cases?: number;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('admin_token') || '';
  const headers = new Headers(init?.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401 && !path.startsWith('/auth/login')) {
    localStorage.removeItem('admin_token');
    if (!location.pathname.startsWith('/login')) location.href = '/login';
    throw new Error('未登录或登录已过期');
  }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      msg = body.detail || msg;
    } catch { /* ignore */ }
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return res.json() as Promise<T>;
}

export interface AdminInfo {
  id: number;
  username: string;
  display_name: string;
  bound_court_user_id: number | null;
  bound_court_account?: string | null;
}

export interface CourtAccount {
  id: number;
  username: string;
  username_masked: string;
  user_type: string;
  is_active: number;
  created_at: string;
  bound_admins: number;
}

export const api = {
  health: () => req<{ ok: boolean; error?: string }>('/health'),
  stats: () => req<Stats>('/stats'),
  cases: (params: { status?: number; q?: string; page?: number; size?: number }) => {
    const sp = new URLSearchParams();
    if (params.status !== undefined && params.status !== null) sp.set('status', String(params.status));
    if (params.q) sp.set('q', params.q);
    sp.set('page', String(params.page ?? 1));
    sp.set('size', String(params.size ?? 20));
    return req<CaseListResp>(`/cases?${sp}`);
  },
  caseDetail: (id: number) => req<CaseDetail>(`/cases/${id}`),
  updateStatus: (id: number, status: number) =>
    req<{ ok: boolean }>(`/cases/${id}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    }),
  importCases: (file: File, dry = false) => {
    const fd = new FormData();
    fd.append('file', file);
    return req<ImportResult>(`/cases/import${dry ? '?dry=1' : ''}`, { method: 'POST', body: fd });
  },
  uploadFiles: (files: { file: File; category: string }[]) => {
    const fd = new FormData();
    files.forEach(({ file, category }) => {
      fd.append('files', file);
      fd.append('categories', category);
    });
    return req<FilesUploadResult>('/files/upload', { method: 'POST', body: fd });
  },
  listFiles: () => req<{ items: UploadedFile[]; categories: string[] }>('/files/list'),
  deleteFile: (name: string) =>
    req<{ ok: boolean }>(`/files/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  folderTemplateUrl: '/files/folder-template',
  templateUrl: '/cases/template',
  startRun: (caseIds: number[]) =>
    req<{ ok: boolean; run_id: string; case_nos: string[] }>('/filing/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ case_ids: caseIds }),
    }),
  runs: () => req<{ items: RunMeta[] }>('/filing/runs'),
  run: (id: string) => req<RunMeta>(`/filing/runs/${id}`),
  runLog: (id: string, offset: number) =>
    req<{ offset: number; text: string; status: string }>(`/filing/runs/${id}/log?offset=${offset}`),
  cancelRun: (id: string) => req<{ ok: boolean }>(`/filing/runs/${id}/cancel`, { method: 'POST' }),
  // 认证与账号
  login: (username: string, password: string) =>
    req<{ ok: boolean; token: string; admin: AdminInfo }>('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }),
  logout: () => req<{ ok: boolean }>('/auth/logout', { method: 'POST' }),
  me: () => req<AdminInfo>('/auth/me'),
  changePassword: (old_password: string, new_password: string) =>
    req<{ ok: boolean }>('/auth/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old_password, new_password }),
    }),
  courtAccounts: () => req<{ items: CourtAccount[]; my_bound_id: number | null }>('/court-accounts'),
  createCourtAccount: (data: { username: string; password: string; user_type: string; is_active: boolean }) =>
    req<{ ok: boolean; id: number }>('/court-accounts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  updateCourtAccount: (id: number, data: { password?: string; user_type?: string; is_active?: boolean }) =>
    req<{ ok: boolean }>(`/court-accounts/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  bindCourtAccount: (id: number) =>
    req<{ ok: boolean; bound_court_user_id: number }>(`/court-accounts/${id}/bind`, { method: 'POST' }),
  unbindCourtAccount: () => req<{ ok: boolean }>('/court-accounts/unbind', { method: 'POST' }),
};
