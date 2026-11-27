#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法院立案管理后台 API 服务

直连法院立案工具的 MySQL 数据库，复用 import_cases_to_db.py 入库与
test_filing_flow.py --from-db 立案链路。

运行：python server/api.py  （默认 0.0.0.0:8100，可用 API_PORT 覆盖）
前端开发模式下由 vite 代理 /api 到本服务；生产模式直接托管 app/dist。
"""
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import pymysql
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent          # app/server
APP_DIR = BASE_DIR.parent                            # app
WORKSPACE = APP_DIR.parent                           # 工作区根
TOOL_DIR = Path(os.environ.get('COURT_TOOL_DIR', WORKSPACE / 'extracted')).resolve()
DIST_DIR = APP_DIR / 'dist'
RUN_LOG_DIR = BASE_DIR / 'run_logs'
UPLOAD_DIR = TOOL_DIR / 'test_data' / 'uploads'
RUNS_META = BASE_DIR / 'runs.json'
for d in (RUN_LOG_DIR, UPLOAD_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ---------------- 配置读取（.env） ----------------

def load_env(path: Path) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

ENV = load_env(TOOL_DIR / '.env')

DB_CONF = dict(
    host=ENV.get('DB_HOST', '127.0.0.1'),
    port=int(ENV.get('DB_PORT', '3306')),
    user=ENV.get('DB_USER', 'root'),
    password=ENV.get('DB_PASSWORD', ''),
    database=ENV.get('DB_NAME', 'court_filing_civil'),
    charset='utf8mb4',
    cursorclass=pymysql.cursors.DictCursor,
)

STATUS_LABEL = {0: '待立案', 1: '已提交', 2: '已驳回', 9: '无需处理'}


def db():
    return pymysql.connect(**DB_CONF)


# ---------------- 管理后台登录与账号绑定 ----------------

def hash_pw(password: str, salt: str) -> str:
    return hashlib.sha256(f'{salt}:{password}'.encode('utf-8')).hexdigest()


def ensure_admin_table():
    """admin_users：管理后台登录账号，bound_court_user_id 绑定 system_users 中的法院账号"""
    with db() as conn, conn.cursor() as cur:
        cur.execute('''CREATE TABLE IF NOT EXISTS admin_users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) NOT NULL UNIQUE,
            password_hash VARCHAR(64) NOT NULL,
            salt VARCHAR(32) NOT NULL,
            display_name VARCHAR(50) DEFAULT '',
            bound_court_user_id INT NULL,
            is_active TINYINT(1) DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        cur.execute('SELECT COUNT(*) n FROM admin_users')
        if cur.fetchone()['n'] == 0:
            salt = secrets.token_hex(8)
            cur.execute('INSERT INTO admin_users (username, password_hash, salt, display_name) VALUES (%s,%s,%s,%s)',
                        ('admin', hash_pw('admin123', salt), salt, '管理员'))
        conn.commit()


SESSIONS_FILE = BASE_DIR / 'sessions.json'
sessions: dict[str, dict] = {}
sessions_lock = threading.Lock()


def load_sessions():
    global sessions
    if SESSIONS_FILE.exists():
        try:
            sessions = json.loads(SESSIONS_FILE.read_text(encoding='utf-8'))
        except Exception:
            sessions = {}


def save_sessions():
    SESSIONS_FILE.write_text(json.dumps(sessions, ensure_ascii=False), encoding='utf-8')


def current_admin(request: Request) -> dict:
    """从 Authorization: Bearer <token> 解析当前登录的管理员"""
    auth = request.headers.get('Authorization', '')
    token = auth[7:] if auth.startswith('Bearer ') else ''
    with sessions_lock:
        sess = sessions.get(token)
    if not sess:
        raise HTTPException(401, '未登录或登录已过期')
    with db() as conn, conn.cursor() as cur:
        cur.execute('''SELECT a.id, a.username, a.display_name, a.bound_court_user_id,
                              s.username AS bound_court_username, s.user_type AS bound_court_user_type
                       FROM admin_users a
                       LEFT JOIN system_users s ON s.id = a.bound_court_user_id
                       WHERE a.id=%s AND a.is_active=1''', (sess['admin_id'],))
        row = cur.fetchone()
    if not row:
        raise HTTPException(401, '账号不存在或已停用')
    return row


class LoginBody(BaseModel):
    username: str
    password: str


def mask_account(username: str) -> str:
    if len(username) >= 7:
        return f'{username[:3]}****{username[-4:]}'
    return username[:1] + '****' if username else ''


# ---------------- 数据校验（与 tests 保持一致） ----------------
WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
CODES = '10X98765432'


def valid_idcard(no: str) -> bool:
    if not no or len(no) != 18 or not no[:17].isdigit():
        return False
    return CODES[sum(int(d) * w for d, w in zip(no[:17], WEIGHTS)) % 11] == no[17].upper()


def validate_cases(data):
    """返回 (cases, errors)。errors 非空则拒绝导入。"""
    errors = []
    if not isinstance(data, list) or not data:
        return [], ['JSON 须为非空案件数组']
    seen = set()
    for i, c in enumerate(data):
        tag = c.get('case_no') or f'第{i + 1}条'
        if c.get('case_no') in seen:
            errors.append(f'{tag} 案件编号重复')
        seen.add(c.get('case_no'))
        for field in ('case_no', 'court_name', 'case_cause'):
            if not c.get(field):
                errors.append(f'{tag} 缺少必填字段 {field}')
        for role in ('plaintiff', 'defendant'):
            p = c.get(role) or {}
            if not p.get('name'):
                errors.append(f'{tag} 缺少{role}')
            # 自然人必须身份证合法；法人（有 uscc 字段或证件非18位身份证）跳过
            idc = p.get('idcard', '')
            if idc and not valid_idcard(idc):
                errors.append(f'{tag} {role} 身份证校验位不合法')
        for a in c.get('agents') or []:
            if a.get('idcard') and not valid_idcard(a['idcard']):
                errors.append(f'{tag} 代理人身份证校验位不合法')
    return data, errors


# ---------------- Excel 解析与材料文件 ----------------
XLSX_HEADERS = {
    '案件编号': 'case_no', '受理法院': 'court_name', '省份': 'court_province',
    '案由': 'case_cause', '标的金额': 'amount', '诉讼请求': 'claims', '事实与理由': 'facts',
    '原告姓名': 'plaintiff.name', '原告身份证': 'plaintiff.idcard', '原告电话': 'plaintiff.phone', '原告地址': 'plaintiff.address',
    '被告姓名': 'defendant.name', '被告身份证': 'defendant.idcard', '被告电话': 'defendant.phone', '被告地址': 'defendant.address',
    '代理人姓名': 'agent.name', '代理人身份证': 'agent.idcard', '代理人电话': 'agent.phone',
    '代理人执业证号': 'agent.license_no', '代理人单位': 'agent.work_unit',
    '材料文件': 'documents',
}

DOC_TYPE_RULES = [('起诉状', '起诉状'), ('complaint', '起诉状'),
                  ('身份证明', '身份证明'), ('身份证', '身份证明'),
                  ('证据', '证据'), ('evidence', '证据'),
                  ('委托', '委托书'), ('authorization', '委托书'),
                  ('送达', '送达地址确认书'), ('service', '送达地址确认书'),
                  ('_id', '身份证明')]

DOC_CATEGORIES = ['起诉状', '身份证明', '证据', '委托书', '送达地址确认书', '其他']

DOC_INDEX_PATH = TOOL_DIR / 'documents' / 'uploads' / '_index.json'


def load_doc_index() -> dict:
    """材料文件名 → 类别 索引（批量上传时由用户指定）"""
    try:
        if DOC_INDEX_PATH.exists():
            return json.loads(DOC_INDEX_PATH.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def save_doc_index(idx: dict):
    DOC_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_INDEX_PATH.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding='utf-8')

DEFAULT_DOCS = [
    ('民事起诉状', '起诉状', 'documents/complaint.pdf'),
    ('原告身份证明', '身份证明', 'documents/plaintiff_id.png'),
    ('被告身份证明', '身份证明', 'documents/defendant_id.png'),
    ('证据目录', '证据', 'documents/evidence_catalog.pdf'),
    ('授权委托书', '委托书', 'documents/authorization.pdf'),
    ('送达地址确认书', '送达地址确认书', 'documents/service_address.pdf'),
]


def doc_type_of(filename: str) -> str:
    low = filename.lower()
    for kw, t in DOC_TYPE_RULES:
        if kw in low or kw in filename:
            return t
    return '证据'


def resolve_doc_path(name: str) -> str | None:
    """材料文件名 → 工具目录下相对路径，找不到返回 None"""
    for cand in (TOOL_DIR / 'documents' / 'uploads' / name, TOOL_DIR / 'documents' / name):
        if cand.exists():
            return str(cand.relative_to(TOOL_DIR)).replace('\\', '/')
    return None


def parse_xlsx_cases(raw: bytes):
    """解析 Excel 案件数据，返回 (cases, errors)"""
    from openpyxl import load_workbook
    import io
    cases, errors = [], []
    try:
        ws = load_workbook(io.BytesIO(raw), read_only=True).active
    except Exception as e:
        return [], [f'Excel 解析失败: {e}']
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        return [], ['Excel 至少需要表头行和一行数据']
    headers = [str(h).strip() if h else '' for h in rows[0]]
    col_map = {}
    for i, h in enumerate(headers):
        key = h.replace('*', '').strip()      # 表头允许「案件编号 *」标注必填
        if key in XLSX_HEADERS:
            col_map[i] = XLSX_HEADERS[key]
    if 'case_no' not in col_map.values():
        return [], ['表头缺少「案件编号」列，请下载模板对照']
    unknown = [h for h in headers if h and h.replace('*', '').strip() not in XLSX_HEADERS]

    def cell(row, key):
        for i, k in col_map.items():
            if k == key and i < len(row):
                v = row[i]
                return str(v).strip() if v is not None else ''
        return ''

    for ridx, row in enumerate(rows[1:], start=2):
        if not any(v is not None and str(v).strip() for v in row):
            continue
        tag = cell(row, 'case_no') or f'第{ridx}行'
        doc_names = [n.strip() for n in re.split(r'[;；,，]', cell(row, 'documents')) if n.strip()]
        doc_index = load_doc_index()
        docs, missing = [], []
        for n in doc_names:
            rel = resolve_doc_path(n)
            if rel:
                # 类别优先取上传时用户指定的索引，其次按文件名推断
                docs.append({'name': os.path.splitext(n)[0], 'type': doc_index.get(n) or doc_type_of(n), 'path': rel})
            else:
                missing.append(n)
        if not doc_names:
            docs = [{'name': n, 'type': t, 'path': p} for n, t, p in DEFAULT_DOCS]
        if missing:
            errors.append(f'{tag} 材料文件未找到（先批量上传材料）：{", ".join(missing)}')
        agent_name = cell(row, 'agent.name')
        case = {
            'case_no': tag, 'case_type': '民事案件', 'court_code': 'beijing',
            'court_name': cell(row, 'court_name'),
            'court_province': cell(row, 'court_province') or '北京',
            'case_cause': cell(row, 'case_cause'),
            'amount': float(cell(row, 'amount') or 0),
            'claims': cell(row, 'claims'), 'facts': cell(row, 'facts'),
            'plaintiff': {'name': cell(row, 'plaintiff.name'), 'idcard': cell(row, 'plaintiff.idcard'),
                          'phone': cell(row, 'plaintiff.phone'), 'address': cell(row, 'plaintiff.address')},
            'defendant': {'name': cell(row, 'defendant.name'), 'idcard': cell(row, 'defendant.idcard'),
                          'phone': cell(row, 'defendant.phone'), 'address': cell(row, 'defendant.address')},
            'documents': docs,
            'agents': ([{'name': agent_name, 'idcard': cell(row, 'agent.idcard'),
                         'phone': cell(row, 'agent.phone'), 'type': '执业律师',
                         'license_no': cell(row, 'agent.license_no'),
                         'work_unit': cell(row, 'agent.work_unit'),
                         'principals': [cell(row, 'plaintiff.name')]}] if agent_name else []),
        }
        cases.append(case)
    if unknown:
        errors.append(f'未识别的表头（已忽略）：{", ".join(unknown)}')
    return cases, errors


def make_template() -> bytes:
    """生成 Excel 导入模板（数据 sheet + 填写说明 sheet）"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    import io
    wb = Workbook()
    ws = wb.active
    ws.title = '案件数据'
    required = {'案件编号', '受理法院', '案由', '原告姓名', '被告姓名'}
    headers = list(XLSX_HEADERS.keys())
    ws.append([h + (' *' if h in required else '') for h in headers])
    ws.append(['TEST-2026-XLS-001', '北京市海淀区人民法院', '北京', '民间借贷纠纷', 50000,
               '判令被告归还借款50000元及利息。', '2025年1月被告向原告借款50000元……',
               '张三', '11010119900101001X', '13800000001', '北京市海淀区xx路1号',
               '李四', '110101198502020022', '13800000002', '北京市朝阳区xx路2号',
               '王律师', '110101198003154325', '13700000003', '11101202110456721', '北京大成律师事务所',
               '民事起诉状.pdf;张三身份证.png;李四身份证.png;借款证据材料.pdf;授权委托书.pdf;送达地址确认书.pdf'])
    hdr_fill = PatternFill('solid', fgColor='1E2A45')
    hdr_font = Font(color='FFFFFF', bold=True)
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i)
        c.fill, c.font = hdr_fill, hdr_font
        c.alignment = Alignment(horizontal='center')
        ws.column_dimensions[c.column_letter].width = max(12, len(h) * 2 + 4)

    ws2 = wb.create_sheet('填写说明')
    notes = [
        ['列名', '说明'],
        ['案件编号 *', '业务唯一编号，重复导入同一编号会更新原案件（不会重复）'],
        ['受理法院 *', '法院全称，如 昆明市五华区人民法院'],
        ['省份', '受理法院所在省/直辖市/自治区，如 云南、重庆、新疆；留空默认北京'],
        ['案由 *', '立案案由，如 买卖合同纠纷 / 民间借贷纠纷 / 房屋租赁合同纠纷 / 机动车交通事故责任纠纷 / 服务合同纠纷'],
        ['标的金额', '数字，单位元'],
        ['诉讼请求 / 事实与理由', '起诉状正文内容'],
        ['原告/被告 姓名 *', '自然人填姓名；身份证须为合法 18 位号码（校验位正确）'],
        ['代理人', '可留空；填写后类型默认为执业律师，被代理人默认为原告'],
        ['材料文件', '文件名列表，分号分隔；需先在后台「数据上传 → 材料文件批量上传」中上传并指定类别；留空则使用默认六份材料'],
        ['材料类别', '起诉状 / 身份证明 / 证据 / 委托书 / 送达地址确认书 / 其他'],
    ]
    for row in notes:
        ws2.append(row)
    ws2.column_dimensions['A'].width = 22
    ws2.column_dimensions['B'].width = 100
    for c in ws2[1]:
        c.fill, c.font = hdr_fill, hdr_font

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------- 立案运行管理 ----------------
runs = {}          # run_id -> dict(meta)
runs_lock = threading.Lock()


def load_runs_meta():
    if RUNS_META.exists():
        try:
            for r in json.loads(RUNS_META.read_text(encoding='utf-8')):
                if r.get('status') == 'running':
                    r['status'] = 'interrupted'   # 服务重启后旧进程已不存在
                runs[r['id']] = r
        except Exception:
            pass


def save_runs_meta():
    try:
        RUNS_META.write_text(json.dumps(list(runs.values()), ensure_ascii=False, indent=1),
                             encoding='utf-8')
    except Exception:
        pass


load_runs_meta()
load_sessions()
ensure_admin_table()

app = FastAPI(title='法院立案管理后台 API')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])


PUBLIC_API = {'/api/health', '/api/auth/login', '/api/cases/template', '/api/files/folder-template', '/api/preserve/template'}


@app.middleware('http')
async def auth_gate(request: Request, call_next):
    """除登录/健康检查外，所有 /api/* 请求需要 Bearer token"""
    if request.method != 'OPTIONS' and request.url.path.startswith('/api/') \
            and request.url.path not in PUBLIC_API:
        auth = request.headers.get('Authorization', '')
        token = auth[7:] if auth.startswith('Bearer ') else ''
        with sessions_lock:
            ok = token in sessions
        if not ok:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail': '未登录或登录已过期'}, status_code=401)
    return await call_next(request)


# ---------------- 登录认证与法院账号管理 ----------------

@app.post('/api/auth/login')
def login(body: LoginBody):
    with db() as conn, conn.cursor() as cur:
        cur.execute('SELECT * FROM admin_users WHERE username=%s AND is_active=1', (body.username,))
        row = cur.fetchone()
    if not row or hash_pw(body.password, row['salt']) != row['password_hash']:
        raise HTTPException(401, '用户名或密码错误')
    token = secrets.token_urlsafe(24)
    with sessions_lock:
        sessions[token] = {'admin_id': row['id'], 'login_at': datetime.now().isoformat(timespec='seconds')}
        save_sessions()
    return {'ok': True, 'token': token,
            'admin': {'id': row['id'], 'username': row['username'], 'display_name': row['display_name'],
                      'bound_court_user_id': row['bound_court_user_id']}}


@app.post('/api/auth/logout')
def logout(request: Request):
    auth = request.headers.get('Authorization', '')
    token = auth[7:] if auth.startswith('Bearer ') else ''
    with sessions_lock:
        sessions.pop(token, None)
        save_sessions()
    return {'ok': True}


@app.get('/api/auth/me')
def auth_me(admin: dict = Depends(current_admin)):
    return {'id': admin['id'], 'username': admin['username'], 'display_name': admin['display_name'],
            'bound_court_user_id': admin['bound_court_user_id'],
            'bound_court_account': mask_account(admin['bound_court_username'] or '') or None}


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


@app.post('/api/auth/password')
def change_password(body: PasswordChange, admin: dict = Depends(current_admin)):
    if len(body.new_password) < 6:
        raise HTTPException(400, '新密码至少 6 位')
    with db() as conn, conn.cursor() as cur:
        cur.execute('SELECT password_hash, salt FROM admin_users WHERE id=%s', (admin['id'],))
        row = cur.fetchone()
        if hash_pw(body.old_password, row['salt']) != row['password_hash']:
            raise HTTPException(400, '原密码错误')
        salt = secrets.token_hex(8)
        cur.execute('UPDATE admin_users SET password_hash=%s, salt=%s WHERE id=%s',
                    (hash_pw(body.new_password, salt), salt, admin['id']))
        conn.commit()
    return {'ok': True}


# ---- 法院账号（system_users）管理 ----

@app.get('/api/court-accounts')
def list_court_accounts(admin: dict = Depends(current_admin)):
    with db() as conn, conn.cursor() as cur:
        cur.execute('''SELECT id, username, user_type, is_active, created_at,
                              (SELECT COUNT(*) FROM admin_users a WHERE a.bound_court_user_id = system_users.id) AS bound_admins
                       FROM system_users ORDER BY id''')
        rows = cur.fetchall()
    for r in rows:
        r['username_masked'] = mask_account(r['username'])
    return {'items': rows, 'my_bound_id': admin['bound_court_user_id']}


class CourtAccountBody(BaseModel):
    username: str
    password: str
    user_type: str = '个人用户'
    is_active: bool = True


@app.post('/api/court-accounts')
def create_court_account(body: CourtAccountBody, admin: dict = Depends(current_admin)):
    if not body.username.strip() or not body.password:
        raise HTTPException(400, '账号和密码不能为空')
    with db() as conn, conn.cursor() as cur:
        cur.execute('SELECT id FROM system_users WHERE username=%s', (body.username.strip(),))
        if cur.fetchone():
            raise HTTPException(409, '该账号已存在')
        cur.execute('INSERT INTO system_users (username, password, user_type, is_active) VALUES (%s,%s,%s,%s)',
                    (body.username.strip(), body.password, body.user_type, 1 if body.is_active else 0))
        conn.commit()
        new_id = cur.lastrowid
    return {'ok': True, 'id': new_id}


class CourtAccountPatch(BaseModel):
    password: str | None = None
    user_type: str | None = None
    is_active: bool | None = None


@app.patch('/api/court-accounts/{account_id}')
def update_court_account(account_id: int, body: CourtAccountPatch, admin: dict = Depends(current_admin)):
    sets, args = [], []
    if body.password:
        sets.append('password=%s'); args.append(body.password)
    if body.user_type is not None:
        sets.append('user_type=%s'); args.append(body.user_type)
    if body.is_active is not None:
        sets.append('is_active=%s'); args.append(1 if body.is_active else 0)
    if not sets:
        raise HTTPException(400, '没有要更新的字段')
    args.append(account_id)
    with db() as conn, conn.cursor() as cur:
        cur.execute(f'UPDATE system_users SET {", ".join(sets)} WHERE id=%s', args)
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, '账号不存在')
    return {'ok': True}


@app.post('/api/court-accounts/{account_id}/bind')
def bind_court_account(account_id: int, admin: dict = Depends(current_admin)):
    """把某个法院账号绑定为当前登录管理员的立案账号"""
    with db() as conn, conn.cursor() as cur:
        cur.execute('SELECT id, is_active FROM system_users WHERE id=%s', (account_id,))
        acc = cur.fetchone()
        if not acc:
            raise HTTPException(404, '账号不存在')
        if not acc['is_active']:
            raise HTTPException(400, '该账号已停用，不能绑定')
        cur.execute('UPDATE admin_users SET bound_court_user_id=%s WHERE id=%s', (account_id, admin['id']))
        conn.commit()
    return {'ok': True, 'bound_court_user_id': account_id}


@app.post('/api/court-accounts/unbind')
def unbind_court_account(admin: dict = Depends(current_admin)):
    with db() as conn, conn.cursor() as cur:
        cur.execute('UPDATE admin_users SET bound_court_user_id=NULL WHERE id=%s', (admin['id'],))
        conn.commit()
    return {'ok': True}


# ---------------- 案件查询 ----------------

@app.get('/api/health')
def health():
    try:
        with db() as conn:
            conn.ping()
        return {'ok': True, 'tool_dir': str(TOOL_DIR)}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@app.get('/api/stats')
def stats():
    with db() as conn, conn.cursor() as cur:
        cur.execute('SELECT status, COUNT(*) n FROM cases GROUP BY status')
        by_status = {STATUS_LABEL.get(r['status'], r['status']): r['n'] for r in cur.fetchall()}
        cur.execute('SELECT COUNT(*) n FROM cases')
        total = cur.fetchone()['n']
        cur.execute('SELECT COUNT(*) n FROM agents')
        agents_n = cur.fetchone()['n']
        cur.execute('SELECT COUNT(*) n FROM case_files')
        files_n = cur.fetchone()['n']
        cur.execute('SELECT COUNT(DISTINCT court_province) n FROM cases')
        prov_n = cur.fetchone()['n']
        cur.execute("SELECT COALESCE(NULLIF(court_province,''),'未填') p, COUNT(*) n FROM cases GROUP BY p ORDER BY n DESC LIMIT 12")
        by_province = [{'province': r['p'], 'count': r['n']} for r in cur.fetchall()]
    return {'total': total, 'by_status': by_status, 'agents': agents_n,
            'files': files_n, 'provinces': prov_n, 'by_province': by_province}


@app.get('/api/cases')
def list_cases(status: int | None = None, q: str = '', page: int = 1, size: int = 20):
    where, args = [], []
    if status is not None:
        where.append('status=%s')
        args.append(status)
    if q:
        where.append('(case_no LIKE %s OR court_name LIKE %s OR applicant_name LIKE %s OR respondent_name LIKE %s OR case_reason LIKE %s)')
        args += [f'%{q}%'] * 5
    wsql = ('WHERE ' + ' AND '.join(where)) if where else ''
    with db() as conn, conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) n FROM cases {wsql}', args)
        total = cur.fetchone()['n']
        cur.execute(f'''SELECT id, case_no, case_type, court_name, court_province, case_reason,
                        claim_amount, applicant_name, applicant_nature, respondent_name,
                        status, created_at
                        FROM cases {wsql} ORDER BY id DESC LIMIT %s OFFSET %s''',
                    args + [size, (page - 1) * size])
        rows = cur.fetchall()
    for r in rows:
        r['status_label'] = STATUS_LABEL.get(r['status'], str(r['status']))
        r['claim_amount'] = float(r['claim_amount'] or 0)
        r['created_at'] = str(r['created_at'])
    return {'total': total, 'page': page, 'size': size, 'items': rows}


# ---------------- 保全案件 ----------------

class StatusUpdate(BaseModel):
    status: int


PRESERVE_STATUS_LABEL = {0: '待提交', 1: '已提交'}


@app.get('/api/preserve/cases')
def list_preserve_cases(status: int | None = None, q: str = '', page: int = 1, size: int = 20):
    where, args = [], []
    if status is not None:
        where.append('status=%s')
        args.append(status)
    if q:
        where.append('(case_no LIKE %s OR case_name LIKE %s OR court_name LIKE %s OR applicant_name LIKE %s OR respondent_name LIKE %s)')
        args += [f'%{q}%'] * 5
    wsql = ('WHERE ' + ' AND '.join(where)) if where else ''
    with db() as conn, conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) n FROM preserve_cases {wsql}', args)
        total = cur.fetchone()['n']
        cur.execute(f'''SELECT c.id, c.case_no, c.case_name, c.preserve_category, c.preserve_amount,
                        c.court_name, c.applicant_name, c.respondent_name, c.guarantee_type,
                        c.status, c.created_at,
                        (SELECT COUNT(*) FROM preserve_property_clues p WHERE p.case_id=c.id) AS property_count,
                        (SELECT COUNT(*) FROM preserve_case_files f WHERE f.case_id=c.id) AS file_count
                        FROM preserve_cases c {wsql} ORDER BY c.id DESC LIMIT %s OFFSET %s''',
                    args + [size, (page - 1) * size])
        rows = cur.fetchall()
    for r in rows:
        r['status_label'] = PRESERVE_STATUS_LABEL.get(r['status'], str(r['status']))
        r['preserve_amount'] = float(r['preserve_amount'] or 0)
        r['created_at'] = str(r['created_at'])
    return {'total': total, 'page': page, 'size': size, 'items': rows}


@app.get('/api/preserve/cases/{case_id}')
def preserve_case_detail(case_id: int):
    with db() as conn, conn.cursor() as cur:
        cur.execute('SELECT * FROM preserve_cases WHERE id=%s', (case_id,))
        case = cur.fetchone()
        if not case:
            raise HTTPException(404, '案件不存在')
        cur.execute('SELECT * FROM preserve_property_clues WHERE case_id=%s', (case_id,))
        props = cur.fetchall()
        cur.execute('SELECT * FROM preserve_case_files WHERE case_id=%s', (case_id,))
        files = cur.fetchall()
        cur.execute('SELECT * FROM preserve_agents WHERE case_id=%s', (case_id,))
        agents = cur.fetchall()
    case['status_label'] = PRESERVE_STATUS_LABEL.get(case['status'], str(case['status']))
    rows = list(case and [case] or []) + list(props) + list(files) + list(agents)
    for r in rows:
        for k, v in r.items():
            if isinstance(v, datetime):
                r[k] = str(v)
            elif hasattr(v, 'real'):  # Decimal
                r[k] = float(v)
    return {'case': case, 'properties': props, 'files': files, 'agents': agents}


@app.patch('/api/preserve/cases/{case_id}/status')
def update_preserve_status(case_id: int, body: StatusUpdate):
    if body.status not in PRESERVE_STATUS_LABEL:
        raise HTTPException(400, '非法状态值')
    with db() as conn, conn.cursor() as cur:
        cur.execute('UPDATE preserve_cases SET status=%s WHERE id=%s', (body.status, case_id))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, '案件不存在')
    return {'ok': True}


# ---------------- 保全案件 Excel 模板与批量导入（参照原保全系统 admin_app.py） ----------------
# (字段key, 表头, 是否必填)；主行=案件编号非空，从行=编号留空、归属上一主行（追加财产/代理人）
PRESERVE_TEMPLATE_COLUMNS = [
    ('case_no', '案件编号*', True), ('case_name', '案件名称*', True), ('preserve_type', '保全类别', False),
    ('case_reason', '案由', False), ('court_name', '申请法院*', True), ('preserve_amount', '保全金额*', True),
    ('delivery_address', '送达地址', False), ('contact_name', '联系人姓名', False), ('contact_phone', '联系人电话', False),
    ('remark', '备注', False), ('applicant_type', '申请人类型', False), ('applicant_name', '申请人姓名*', True),
    ('applicant_cert_no', '申请人身份证号*', True), ('applicant_gender', '申请人性别', False),
    ('applicant_phone', '申请人手机号*', True), ('applicant_address', '申请人地址', False),
    ('applicant_uscc', '申请人统一社会信用代码', False),
    ('applicant_nature', '申请人单位性质', False),
    ('applicant_legal_person', '申请人法定代表人', False),
    ('applicant_legal_title', '申请人法定代表人职务', False),
    ('applicant_reg_address', '申请人单位注册地', False),
    ('applicant_tel', '申请人固定电话', False), ('applicant_email', '申请人邮箱', False),
    ('applicant_birth', '申请人生日', False), ('applicant_age', '申请人年龄', False),
    ('applicant_nation', '申请人民族', False), ('applicant_household_address', '申请人户籍地址', False),
    ('respondent_type', '被申请人类型', False), ('respondent_name', '被申请人姓名*', True),
    ('respondent_id', '被申请人身份证号*', True), ('respondent_gender', '被申请人性别', False),
    ('respondent_uscc', '被申请人统一社会信用代码', False),
    ('respondent_phone', '被申请人手机号', False), ('respondent_address', '被申请人地址', False),
    ('respondent_tel', '被申请人固定电话', False), ('respondent_residence', '被申请人经常居住地', False),
    ('respondent_nature', '被申请人性质', False), ('respondent_legal_person', '被申请人法定代表人', False),
    ('respondent_legal_title', '被申请人法定职务', False), ('respondent_reg_address', '被申请人户籍地址', False),
    ('property_type', '财产类型*', True), ('property_owner', '财产所有人', False),
    ('bank_name', '开户银行', False), ('bank_account', '银行账号', False), ('amount', '数额', False),
    ('currency', '币种', False), ('property_value', '财产价值', False), ('property_province', '财产所在省份', False),
    ('property_city', '财产所在城市', False), ('property_location', '财产详细地址', False),
    ('property_cert_no', '产权证号', False), ('property_detail_location', '财产具体位置', False),
    ('vehicle_plate_no', '车牌号', False), ('vehicle_location', '车辆位置', False),
    ('stock_name', '股票名称', False), ('stock_code', '股票代码', False), ('stock_quantity', '持股数量', False),
    ('stock_reg_location', '发行单位注册地', False), ('stock_company_name', '持股公司名称', False),
    ('stock_ratio', '出资比例', False), ('equipment_name', '设备名称', False),
    ('property_area', '土地面积', False), ('property_area_unit', '面积单位', False),
    ('fund_name', '基金名称', False), ('fund_quantity', '基金数量', False),
    ('bond_name', '债券名称', False), ('bond_face_value', '债券面值', False),
    ('description', '财产描述', False),
    ('guarantee_type', '担保方式', False), ('guarantee_value', '担保价值', False),
    ('guarantor_name', '担保人姓名', False), ('guarantee_object', '担保物名称', False),
    ('guarantee_property_type', '担保财产类型', False), ('guarantee_remark', '担保备注', False),
    ('agent_type', '代理人类型', False), ('agent_name', '代理人姓名', False),
    ('agent_cert_no', '代理人身份证号', False), ('agent_phone', '代理人电话', False),
    ('agent_license_no', '代理人执业证号', False), ('agent_law_firm', '代理人律所', False),
]
PRESERVE_HEADER_MAP = {h.replace('*', ''): k for k, h, _ in PRESERVE_TEMPLATE_COLUMNS}
PRESERVE_HEADER_OF = {k: h.replace('*', '') for k, h, _ in PRESERVE_TEMPLATE_COLUMNS}
PRESERVE_REQUIRED = ('case_no', 'case_name', 'court_name', 'preserve_amount',
                     'applicant_name', 'applicant_cert_no', 'respondent_name', 'respondent_id',
                     'property_type')

# 各财产类型在法院网站表单上的专属必填项（2026-11-27 真实登录网站逐类型探测，
# 见 extracted/results/probe_property_types.json）；「发行单位注册地/车辆归属地/开户行所在地」
# 等下拉均为省级选项，填省份（如 江苏省）。通用必填（财产类型/所有人/财产价值）不在此列。
PRESERVE_PROP_REQUIRED = {
    '货币现金': [],
    '存款': ['property_province', 'bank_name', 'bank_account'],
    '交通运输工具': ['property_province', 'vehicle_plate_no'],
    '车辆': ['property_province', 'vehicle_plate_no'],
    '汽车': ['property_province', 'vehicle_plate_no'],
    '房产': ['property_province'],
    '土地使用权': ['property_location', 'property_area'],
    '股票': ['stock_reg_location', 'stock_name'],
    '基金': ['stock_reg_location', 'fund_name'],
    '债券': ['stock_reg_location', 'bond_name', 'bond_face_value'],
    '股权': ['stock_company_name', 'stock_reg_location', 'stock_ratio'],
    '机器设备': ['equipment_name'],
}
# 债权 / 产品、原材料 / 知识产权 / 古玩字画 / 森林、林木所有权 / 集体土地所有权 /
# 珠宝玉石首饰 / 探矿、采矿权 / 船舶 / 船载货物 / 船用燃料 / 船用物料 / 留置的货物 / 其他
# 上述类型网站均要求填「描述」
PRESERVE_PROP_DESC_REQUIRED = ('债权', '产品、原材料', '知识产权', '古玩字画', '森林、林木所有权',
                               '集体土地所有权', '珠宝玉石首饰', '探矿、采矿权', '船舶',
                               '船载货物', '船用燃料', '船用物料', '留置的货物', '其他')


def _check_property_required(rd: dict) -> list[str]:
    """按财产类型校验专属必填项，返回缺失字段的中文表头列表"""
    ptype = rd.get('property_type', '')
    missing = [PRESERVE_HEADER_OF[f] for f in PRESERVE_PROP_REQUIRED.get(ptype, []) if not rd.get(f)]
    if ptype in PRESERVE_PROP_DESC_REQUIRED and not rd.get('description'):
        missing.append('财产描述')
    return missing


def _pnum(v):
    """数值解析：空/非法返回 None"""
    if v is None or str(v).strip() in ('', 'nan'):
        return None
    try:
        return float(str(v).replace(',', '').replace('%', ''))
    except (TypeError, ValueError):
        return None


def parse_preserve_xlsx(raw: bytes):
    """解析保全案件 Excel（主行/从行模式），返回 (cases, errors)。
    cases[i] = {'row': 主行字段dict, 'subs': [从行字段dict, ...]}"""
    from openpyxl import load_workbook
    import io
    cases, errors = [], []
    try:
        ws = load_workbook(io.BytesIO(raw), read_only=True).active
    except Exception as e:
        return [], [f'Excel 解析失败: {e}']
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        return [], ['Excel 至少需要表头行和一行数据']
    headers = [str(h).strip() if h else '' for h in rows[0]]
    col_map = {}
    for i, h in enumerate(headers):
        key = h.replace('*', '').strip()
        if key in PRESERVE_HEADER_MAP:
            col_map[i] = PRESERVE_HEADER_MAP[key]
    if 'case_no' not in col_map.values():
        return [], ['表头缺少「案件编号」列，请下载保全导入模板对照']
    unknown = [h for h in headers if h and h.replace('*', '').strip() not in PRESERVE_HEADER_MAP]

    for ridx, row in enumerate(rows[1:], start=2):
        if not any(v is not None and str(v).strip() for v in row):
            continue
        rd = {}
        for i, v in enumerate(row):
            if i in col_map and v is not None and str(v).strip():
                rd[col_map[i]] = str(v).strip()
        case_no = rd.get('case_no', '')
        if case_no:
            missing = [PRESERVE_HEADER_OF[f] for f in PRESERVE_REQUIRED if not rd.get(f)]
            if missing:
                errors.append(f'{case_no}（第{ridx}行）缺少必填字段：{", ".join(missing)}')
                continue
            prop_missing = _check_property_required(rd)
            if prop_missing:
                errors.append(f'{case_no}（第{ridx}行）财产类型「{rd.get("property_type")}」缺少专属必填项：{", ".join(prop_missing)}')
                continue
            cases.append({'row': rd, 'subs': []})
        else:
            if not cases:
                errors.append(f'第{ridx}行：案件编号为空且前面没有主行，无法识别归属')
                continue
            if rd.get('property_type'):
                prop_missing = _check_property_required(rd)
                if prop_missing:
                    errors.append(f'{cases[-1]["row"]["case_no"]}（第{ridx}行）从行财产类型「{rd.get("property_type")}」缺少专属必填项：{", ".join(prop_missing)}')
                    continue
                cases[-1]['subs'].append(rd)
            elif rd.get('agent_name'):
                cases[-1]['subs'].append(rd)
            else:
                errors.append(f'第{ridx}行：从行未填写财产类型或代理人姓名，已跳过')
    if unknown:
        errors.append(f'未识别的表头（已忽略）：{", ".join(unknown)}')
    return cases, errors


def _preserve_case_fields(rd: dict) -> dict:
    """Excel 行 → preserve_cases 字段"""
    gt = rd.get('guarantee_type', '') or '提供保证人'
    pt = rd.get('preserve_type', '') or '诉讼保全'
    return {
        'case_no': rd.get('case_no', ''),
        'case_name': rd.get('case_name', ''),
        'preserve_type': pt,
        'preserve_category': pt,
        'case_reason': rd.get('case_reason', ''),
        'court_name': rd.get('court_name', ''),
        'preserve_amount': _pnum(rd.get('preserve_amount')) or 0,
        'delivery_address': rd.get('delivery_address', ''),
        'contact_name': rd.get('contact_name', ''),
        'contact_phone': rd.get('contact_phone', ''),
        'remark': rd.get('remark', ''),
        'applicant_type': rd.get('applicant_type', '') or '自然人',
        'applicant_name': rd.get('applicant_name', ''),
        'applicant_cert_type': '身份证',
        'applicant_cert_no': rd.get('applicant_cert_no', ''),
        'applicant_gender': rd.get('applicant_gender', ''),
        'applicant_phone': rd.get('applicant_phone', ''),
        'applicant_address': rd.get('applicant_address', ''),
        'applicant_uscc': rd.get('applicant_uscc', ''),
        'applicant_nature': rd.get('applicant_nature', ''),
        'applicant_legal_person': rd.get('applicant_legal_person', ''),
        'applicant_legal_title': rd.get('applicant_legal_title', ''),
        'applicant_reg_address': rd.get('applicant_reg_address', '') or rd.get('applicant_household_address', ''),
        'applicant_tel': rd.get('applicant_tel', ''),
        'applicant_email': rd.get('applicant_email', ''),
        'applicant_birth': rd.get('applicant_birth') or None,
        'applicant_age': _pnum(rd.get('applicant_age')),
        'applicant_nation': rd.get('applicant_nation', '') or '汉族',
        'applicant_country': '中国',
        'respondent_type': rd.get('respondent_type', '') or '自然人',
        'respondent_name': rd.get('respondent_name', ''),
        'respondent_id': rd.get('respondent_id', ''),
        'respondent_cert_type': '身份证',
        'respondent_uscc': rd.get('respondent_uscc', ''),
        'respondent_gender': rd.get('respondent_gender', ''),
        'respondent_phone': rd.get('respondent_phone', ''),
        'respondent_address': rd.get('respondent_address', ''),
        'respondent_tel': rd.get('respondent_tel', ''),
        'respondent_residence': rd.get('respondent_residence', ''),
        'respondent_nature': rd.get('respondent_nature', ''),
        'respondent_legal_person': rd.get('respondent_legal_person', ''),
        'respondent_legal_title': rd.get('respondent_legal_title', ''),
        'respondent_reg_address': rd.get('respondent_reg_address', ''),
        'respondent_country': '中国',
        'guarantee_type': gt,
        'guarantee_value': _pnum(rd.get('guarantee_value')) or 0,
        'guarantor_name': rd.get('guarantor_name', ''),
        'guarantee_object': rd.get('guarantee_object', ''),
        'guarantee_property_type': rd.get('guarantee_property_type', ''),
        'pledge_property_type': rd.get('guarantee_property_type', '') if gt == '设定质押' else '',
        'mortgage_property_type': rd.get('guarantee_property_type', '') if gt == '设定抵押' else '',
        'guarantee_remark': rd.get('guarantee_remark', ''),
        'has_guarantee': 1,
        'created_by': 'excel_import',
    }


def _preserve_property_fields(case_id: int, rd: dict) -> dict:
    """Excel 行 → preserve_property_clues 字段"""
    return {
        'case_id': case_id,
        'property_type': rd.get('property_type', '') or '存款',
        'owner': rd.get('property_owner', '') or rd.get('respondent_name', ''),
        'bank_name': rd.get('bank_name', ''),
        'bank_account': rd.get('bank_account', ''),
        'amount': _pnum(rd.get('amount')) or _pnum(rd.get('preserve_amount')) or 0,
        'currency': rd.get('currency', '') or 'CNY',
        'property_value': _pnum(rd.get('property_value')) or _pnum(rd.get('preserve_amount')) or 0,
        'property_province': rd.get('property_province', ''),
        'property_city': rd.get('property_city', ''),
        'property_location': rd.get('property_location', ''),
        'property_cert_no': rd.get('property_cert_no', ''),
        'property_detail_location': rd.get('property_detail_location', ''),
        'vehicle_plate_no': rd.get('vehicle_plate_no', ''),
        'vehicle_location': rd.get('vehicle_location', ''),
        'stock_name': rd.get('stock_name', ''),
        'stock_code': rd.get('stock_code', ''),
        'stock_quantity': _pnum(rd.get('stock_quantity')),
        'stock_reg_location': rd.get('stock_reg_location', ''),
        'stock_company_name': rd.get('stock_company_name', ''),
        'stock_ratio': _pnum(rd.get('stock_ratio')),
        'equipment_name': rd.get('equipment_name', ''),
        'property_area': _pnum(rd.get('property_area')),
        'property_area_unit': rd.get('property_area_unit', '') or ('平方米' if rd.get('property_area') else ''),
        'fund_name': rd.get('fund_name', ''),
        'fund_quantity': _pnum(rd.get('fund_quantity')),
        'bond_name': rd.get('bond_name', ''),
        'bond_face_value': _pnum(rd.get('bond_face_value')),
        'description': rd.get('description', ''),
    }


def _insert_row(cur, table: str, data: dict) -> int:
    ks = list(data.keys())
    cur.execute(f"INSERT INTO {table} ({','.join(ks)}) VALUES ({','.join(['%s'] * len(ks))})",
                [data[k] for k in ks])
    return cur.lastrowid


def _insert_preserve_agent(cur, case_id: int, rd: dict):
    if not rd.get('agent_name'):
        return
    _insert_row(cur, 'preserve_agents', {
        'case_id': case_id,
        'agent_type': rd.get('agent_type', '') or '律师',
        'agent_name': rd.get('agent_name', ''),
        'agent_cert_no': rd.get('agent_cert_no', ''),
        'agent_phone': rd.get('agent_phone', ''),
        'agent_license_no': rd.get('agent_license_no', ''),
        'agent_law_firm': rd.get('agent_law_firm', ''),
    })


def make_preserve_template() -> bytes:
    """生成保全案件 Excel 导入模板（数据 sheet + 填写说明 sheet），样式参照原保全系统"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    import io
    wb = Workbook()
    ws = wb.active
    ws.title = '保全案件模板'
    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='1a237e', end_color='1a237e', fill_type='solid')
    required_fill = PatternFill(start_color='ffebee', end_color='ffebee', fill_type='solid')
    thin = Border(*[Side(style='thin')] * 4)
    headers = [h for _, h, _ in PRESERVE_TEMPLATE_COLUMNS]
    ws.append(headers)
    for idx, (_, _, req) in enumerate(PRESERVE_TEMPLATE_COLUMNS, 1):
        c = ws.cell(row=1, column=idx)
        c.font, c.border = header_font, thin
        c.fill = required_fill if req else header_fill
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        ws.column_dimensions[get_column_letter(idx)].width = max(10, min(24, len(headers[idx - 1]) * 2 + 2))
    # 示例1：主行（完整案件）
    ws.append([
        '保全2026001', '借款合同纠纷', '诉讼保全', '借款合同纠纷',
        '上海市静安区人民法院', '1000000', '北京市朝阳区XX路1号', '张三', '13800138000', '',
        '自然人', '张三', '110101199001011234', '男', '13800138000', '北京市朝阳区XX小区', '', '', '', '', '',
        '010-12345678', 'zhangsan@example.com', '1990-01-01', '36', '汉族', '北京市朝阳区',
        '自然人', '李四', '110101199002022345', '男', '', '13900139000', '北京市海淀区', '', '北京市海淀区', '',
        '', '', '',
        '存款', '李四', '中国工商银行', '6222021234567890123', '1000000', 'CNY', '1000000', '北京', '北京',
        '', '', '', '', '', '', '', '', '', '', '', '',
        '提供保证人', '100000', '王五', '保证人信用担保', '', '',
        '律师', '赵六', '110101198001011111', '13600136000', '11101201901012345', '北京大成律师事务所',
    ])
    # 示例2：从行（为上一案件追加一条财产线索，只填财产列）
    sub = [''] * len(PRESERVE_TEMPLATE_COLUMNS)
    key_idx = {k: i for i, (k, _, _) in enumerate(PRESERVE_TEMPLATE_COLUMNS)}
    sub[key_idx['property_type']] = '房产'
    sub[key_idx['property_owner']] = '李四'
    sub[key_idx['property_location']] = '北京市海淀区XX小区3号楼'
    sub[key_idx['property_cert_no']] = '京房权证海字第12345号'
    sub[key_idx['property_value']] = '2000000'
    ws.append(sub)
    ws.freeze_panes = 'A2'

    ws2 = wb.create_sheet('填写说明')
    for row in [
        ['字段', '说明', '可选值/示例'],
        ['案件编号*', '唯一标识；重复导入同一编号会更新原案件并替换其财产线索/代理人', '保全2026001'],
        ['保全类别', '', '诉讼保全 / 诉前保全'],
        ['申请法院*', '法院全称', '上海市静安区人民法院'],
        ['保全金额* / 担保价值 / 数额', '数字，无需逗号', '1000000'],
        ['申请人/被申请人类型', '', '自然人 / 法人 / 非法人组织；法人填统一社会信用代码'],
        ['担保方式', '', '提供保证人 / 设定抵押 / 设定质押 / 交纳保证金；选质押/抵押时填「担保财产类型」'],
        ['币种', '', 'CNY / USD / EUR'],
        ['', '', ''],
        ['各财产类型的专属必填项', '（2026-11 真实登录法院网站逐类型探测，与网站表单的 * 必填一致）', ''],
        ['货币现金', '数额', '数额留空时默认取保全金额'],
        ['存款', '财产所在省份（开户行所在地）、开户银行、银行账号', '开户行所在地是省级下拉，填省份，如 广东'],
        ['交通运输工具', '财产所在省份（车辆归属地）、车牌号', '归属地填省份，如 四川；车牌号如 川A88T66'],
        ['房产', '财产所在省份（房产坐落位置）', '坐落位置填省份；详细地址、产权证号建议填写'],
        ['土地使用权', '财产详细地址、土地面积', '面积单位默认 平方米'],
        ['股票', '发行单位注册地（省份）、股票名称', '股票代码、持股数量建议填写'],
        ['基金', '发行单位注册地（省份）、基金名称', '基金数量建议填写'],
        ['债券', '发行单位注册地（省份）、债券名称、债券面值', ''],
        ['股权', '持股公司名称、发行单位注册地（省份）、出资比例', '出资比例填数字（15 表示 15%）'],
        ['机器设备', '设备名称', ''],
        ['债权/知识产权/船舶等其他14类', '财产描述', '债权、产品原材料、知识产权、古玩字画、森林林木、集体土地、珠宝玉石、探矿采矿权、船舶、船载货物、船用燃料、船用物料、留置的货物、其他'],
        ['', '所有类型通用必填：财产类型、财产所有人（默认取被申请人）、财产价值（默认取数额或保全金额）', ''],
        ['', '', ''],
        ['多行说明', '同一案件支持多行：', ''],
        ['', '1. 主行：案件编号非空，填写完整案件信息（含第一条财产线索）', ''],
        ['', '2. 从行：案件编号留空，仅填财产列或代理人列，归属上一主行', ''],
        ['', '3. 材料文件不随 Excel 导入，请在「保全案件」页用「批量上传材料」传 zip 包', ''],
    ]:
        ws2.append(row)
    for c in ws2[1]:
        c.font, c.fill = header_font, header_fill
    ws2.column_dimensions['A'].width = 24
    ws2.column_dimensions['B'].width = 62
    ws2.column_dimensions['C'].width = 60
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@app.get('/api/preserve/template')
def download_preserve_template():
    from fastapi.responses import Response
    return Response(content=make_preserve_template(),
                    media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': 'attachment; filename="preserve_import_template.xlsx"'})


@app.post('/api/preserve/import')
async def import_preserve_cases(file: UploadFile = File(...), dry: bool = False):
    """保全案件 Excel 批量导入。dry=1 只解析预览；正式导入按案件编号幂等（已存在则更新并替换财产/代理人）"""
    raw = await file.read()
    fname = fix_filename(file.filename or 'preserve.xlsx')
    if not fname.lower().endswith(('.xlsx', '.xlsm', '.xls')):
        raise HTTPException(400, '请上传 .xlsx 格式的 Excel 文件')
    cases, errors = parse_preserve_xlsx(raw)
    if not cases:
        return {'ok': False, 'errors': errors, 'cases': []}

    nos = [c['row']['case_no'] for c in cases]
    with db() as conn, conn.cursor() as cur:
        qmarks = ','.join(['%s'] * len(nos))
        cur.execute(f'SELECT case_no FROM preserve_cases WHERE case_no IN ({qmarks})', nos)
        existing = {r['case_no'] for r in cur.fetchall()}
    preview = [{
        'case_no': c['row']['case_no'],
        'case_name': c['row'].get('case_name', ''),
        'court_name': c['row'].get('court_name', ''),
        'applicant_name': c['row'].get('applicant_name', ''),
        'respondent_name': c['row'].get('respondent_name', ''),
        'preserve_amount': _pnum(c['row'].get('preserve_amount')) or 0,
        'guarantee_type': c['row'].get('guarantee_type', '') or '提供保证人',
        'properties': 1 + sum(1 for s in c['subs'] if s.get('property_type')),
        'agents': (1 if c['row'].get('agent_name') else 0) + sum(1 for s in c['subs'] if s.get('agent_name')),
        'exists': c['row']['case_no'] in existing,
    } for c in cases]
    if dry:
        return {'ok': True, 'dry': True, 'cases': preview, 'errors': errors}

    created, updated, failed = [], [], []
    with db() as conn, conn.cursor() as cur:
        for c in cases:
            rd = c['row']
            case_no = rd['case_no']
            try:
                cur.execute('SAVEPOINT sp_case')
                fields = _preserve_case_fields(rd)
                if case_no in existing:
                    ks = [k for k in fields if k != 'case_no']
                    cur.execute(f"UPDATE preserve_cases SET {', '.join(f'{k}=%s' for k in ks)} WHERE case_no=%s",
                                [fields[k] for k in ks] + [case_no])
                    cur.execute('SELECT id FROM preserve_cases WHERE case_no=%s', (case_no,))
                    cid = cur.fetchone()['id']
                    cur.execute('DELETE FROM preserve_property_clues WHERE case_id=%s', (cid,))
                    cur.execute('DELETE FROM preserve_agents WHERE case_id=%s', (cid,))
                    updated.append(case_no)
                else:
                    cid = _insert_row(cur, 'preserve_cases', fields)
                    created.append(case_no)
                _insert_row(cur, 'preserve_property_clues', _preserve_property_fields(cid, rd))
                _insert_preserve_agent(cur, cid, rd)
                for sub in c['subs']:
                    if sub.get('property_type'):
                        _insert_row(cur, 'preserve_property_clues', _preserve_property_fields(cid, sub))
                    if sub.get('agent_name'):
                        _insert_preserve_agent(cur, cid, sub)
                cur.execute('RELEASE SAVEPOINT sp_case')
            except Exception as e:
                cur.execute('ROLLBACK TO sp_case')
                failed.append(f'{case_no}: {e}')
        conn.commit()
    return {'ok': not failed, 'created': created, 'updated': updated,
            'failed': failed, 'errors': errors}


# ---------------- 保全案件材料文件 ----------------
# 执行脚本按 file_category 匹配上传槽位（见 preserve_filing_flow.py 材料上传段），
# 类别必须与之一致；文件存 documents/uploads/preserve/<案件编号>/<类别>/，绝对路径入库。
PRESERVE_UPLOAD_DIR = TOOL_DIR / 'documents' / 'uploads' / 'preserve'
PRESERVE_FILE_EXTS = {'.pdf', '.png', '.jpg', '.jpeg', '.doc', '.docx'}


def preserve_file_categories(case: dict) -> list[str]:
    """根据案件当事人和担保方式生成动态材料类别（与原保全系统一致）"""
    cats = ['保全申请书', '起诉状', '立案受理通知书', '证据材料', '其他材料']
    if case.get('applicant_name'):
        cats.append(f"申请人-{case['applicant_name']}-{case.get('applicant_type') or '自然人'}")
    if case.get('respondent_name'):
        cats.append(f"被申请人-{case['respondent_name']}-{case.get('respondent_type') or '自然人'}")
    gt = case.get('guarantee_type') or ''
    if gt == '提供保证人':
        cats.append(f"提供保证人-{case.get('guarantee_object') or '保证人'}")
    elif gt:
        cats.append(gt)
    return cats


def _save_preserve_file(case_no: str, category: str, src_name: str, data: bytes) -> tuple[str, Path]:
    name = re.sub(r'[^\w.\-一-鿿]', '_', src_name)
    out_dir = PRESERVE_UPLOAD_DIR / str(case_no) / category
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / name
    if target.exists():
        stem, ext = os.path.splitext(name)
        name = f'{stem}_{datetime.now():%H%M%S}{ext}'
        target = out_dir / name
    target.write_bytes(data)
    return name, str(target)


@app.get('/api/preserve/cases/{case_id}/file-categories')
def preserve_case_file_categories(case_id: int):
    with db() as conn, conn.cursor() as cur:
        cur.execute('SELECT * FROM preserve_cases WHERE id=%s', (case_id,))
        case = cur.fetchone()
        if not case:
            raise HTTPException(404, '案件不存在')
    return {'categories': preserve_file_categories(case)}


@app.post('/api/preserve/cases/{case_id}/files')
async def upload_preserve_files(case_id: int, files: list[UploadFile] = File(...), category: str = Form(...)):
    """按类别给保全案件上传材料（可多选）"""
    with db() as conn, conn.cursor() as cur:
        cur.execute('SELECT * FROM preserve_cases WHERE id=%s', (case_id,))
        case = cur.fetchone()
        if not case:
            raise HTTPException(404, '案件不存在')
        cats = preserve_file_categories(case)
        if category not in cats:
            raise HTTPException(400, f'材料类别无效，可选：{", ".join(cats)}')
        saved, rejected = [], []
        for f in files:
            raw_name = fix_filename(f.filename or 'file').replace('\\', '/').rsplit('/', 1)[-1]
            ext = os.path.splitext(raw_name)[1].lower()
            if ext not in PRESERVE_FILE_EXTS:
                rejected.append({'name': f.filename, 'reason': f'不支持的类型 {ext}'})
                continue
            data = await f.read()
            if len(data) > 20 * 1024 * 1024:
                rejected.append({'name': f.filename, 'reason': '超过 20MB 限制'})
                continue
            name, path = _save_preserve_file(str(case['case_no']), category, raw_name, data)
            cur.execute('INSERT INTO preserve_case_files (case_id, file_category, file_name, file_path, upload_status) VALUES (%s,%s,%s,%s,1)',
                        (case_id, category, name, path))
            saved.append({'name': name, 'category': category, 'size': len(data)})
        conn.commit()
    return {'ok': not rejected, 'saved': saved, 'rejected': rejected}


@app.delete('/api/preserve/files/{file_id}')
def delete_preserve_file(file_id: int):
    with db() as conn, conn.cursor() as cur:
        cur.execute('SELECT file_path FROM preserve_case_files WHERE id=%s', (file_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, '文件不存在')
        cur.execute('DELETE FROM preserve_case_files WHERE id=%s', (file_id,))
        conn.commit()
    # 只删除本系统上传目录内的物理文件，旧系统迁移来的绝对路径不动
    try:
        p = Path(row['file_path'] or '')
        if p.exists() and PRESERVE_UPLOAD_DIR in p.parents:
            p.unlink()
    except Exception:
        pass
    return {'ok': True}


@app.post('/api/preserve/files/batch')
async def batch_upload_preserve_files(file: UploadFile = File(...)):
    """zip 批量上传保全材料（参照原保全系统）。
    压缩包结构：案件编号/材料类别/文件名，例如 保全2026001/保全申请书/申请书.pdf"""
    fname = fix_filename(file.filename or '')
    if not fname.lower().endswith('.zip'):
        raise HTTPException(400, '请上传 .zip 格式的压缩包')
    import shutil
    import tempfile
    import zipfile
    raw = await file.read()
    tmp = Path(tempfile.mkdtemp(prefix='preserve_zip_'))
    results, skipped = [], []
    total = 0
    try:
        zp = tmp / 'u.zip'
        zp.write_bytes(raw)
        ext_dir = tmp / 'x'
        ext_dir.mkdir()
        with zipfile.ZipFile(zp) as z:
            for zi in z.infolist():
                # Windows 资源管理器打的包中文名是 GBK 编码，zipfile 默认按 cp437 解码会乱码
                try:
                    if not (zi.flag_bits & 0x800):
                        zi.filename = zi.filename.encode('cp437').decode('gbk')
                except Exception:
                    pass
                z.extract(zi, ext_dir)
        with db() as conn, conn.cursor() as cur:
            for case_dir in sorted(ext_dir.iterdir()):
                if not case_dir.is_dir():
                    continue
                case_no = case_dir.name
                cur.execute('SELECT * FROM preserve_cases WHERE case_no=%s', (case_no,))
                case = cur.fetchone()
                if not case:
                    skipped.append(f'{case_no}：案件不存在，已跳过')
                    continue
                cats = preserve_file_categories(case)
                cnt = 0
                for cat_dir in sorted(case_dir.iterdir()):
                    if not cat_dir.is_dir():
                        continue
                    cat = cat_dir.name
                    if cat not in cats:
                        skipped.append(f'{case_no}/{cat}：未知材料类别，已跳过')
                        continue
                    for fp in sorted(cat_dir.iterdir()):
                        if not fp.is_file():
                            continue
                        if fp.suffix.lower() not in PRESERVE_FILE_EXTS:
                            skipped.append(f'{case_no}/{cat}/{fp.name}：不支持的文件类型')
                            continue
                        name, path = _save_preserve_file(case_no, cat, fp.name, fp.read_bytes())
                        cur.execute('INSERT INTO preserve_case_files (case_id, file_category, file_name, file_path, upload_status) VALUES (%s,%s,%s,%s,1)',
                                    (case['id'], cat, name, path))
                        cnt += 1
                        total += 1
                results.append({'case_no': case_no, 'count': cnt})
            conn.commit()
    except zipfile.BadZipFile:
        raise HTTPException(400, 'zip 文件损坏或格式不正确')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {'ok': True, 'results': results, 'skipped': skipped, 'total': total}


@app.get('/api/cases/template')
def download_template():
    """Excel 导入模板下载（须注册在 /api/cases/{case_id} 之前）"""
    from fastapi.responses import Response
    return Response(content=make_template(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': 'attachment; filename="case_import_template.xlsx"'})


@app.get('/api/cases/{case_id}')
def case_detail(case_id: int):
    with db() as conn, conn.cursor() as cur:
        cur.execute('SELECT * FROM cases WHERE id=%s', (case_id,))
        case = cur.fetchone()
        if not case:
            raise HTTPException(404, '案件不存在')
        cur.execute('SELECT * FROM agents WHERE case_id=%s', (case_id,))
        agents = cur.fetchall()
        cur.execute('SELECT * FROM case_files WHERE case_id=%s', (case_id,))
        files = cur.fetchall()
    for r in [case, *agents, *files]:
        for k, v in r.items():
            if isinstance(v, (datetime,)):
                r[k] = str(v)
            elif hasattr(v, '__float__') and not isinstance(v, (int, float, str)):
                r[k] = float(v)
    case['status_label'] = STATUS_LABEL.get(case['status'], str(case['status']))
    return {'case': case, 'agents': agents, 'files': files}


@app.patch('/api/cases/{case_id}/status')
def update_status(case_id: int, body: StatusUpdate):
    if body.status not in STATUS_LABEL:
        raise HTTPException(400, '非法状态')
    with db() as conn, conn.cursor() as cur:
        cur.execute('UPDATE cases SET status=%s WHERE id=%s', (body.status, case_id))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, '案件不存在')
    return {'ok': True}


def fix_filename(name: str) -> str:
    """修复 latin-1 误读 UTF-8/GBK 造成的文件名乱码（curl 等客户端常见）"""
    for enc in ('utf-8', 'gbk'):
        try:
            fixed = name.encode('latin-1').decode(enc)
            if any('一' <= ch <= '鿿' for ch in fixed):
                return fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return name


# ---------------- 数据上传导入 ----------------

@app.get('/api/files/folder-template')
def folder_template():
    """材料文件夹模板：六个类别子文件夹 + 说明，上传时按子文件夹自动归类"""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for cat in DOC_CATEGORIES:
            z.writestr(f'材料模板/{cat}/把{cat}文件放这里.txt',
                       f'把属于「{cat}」的材料文件放进本文件夹，上传整个「材料模板」文件夹即可自动归类。')
        z.writestr('材料模板/使用说明.txt',
                   '1. 把材料文件按类别放进对应子文件夹（起诉状/身份证明/证据/委托书/送达地址确认书/其他）\n'
                   '2. 在管理后台「数据上传 → 材料文件批量上传」点「选择文件夹」，选中本「材料模板」文件夹\n'
                   '3. 每个文件会按所在子文件夹自动归类，仍可在列表中单独调整\n'
                   '4. 支持 pdf / png / jpg，单个文件 ≤ 20MB\n')
    buf.seek(0)
    from fastapi.responses import Response
    return Response(content=buf.read(), media_type='application/zip',
                    headers={'Content-Disposition': 'attachment; filename="folder_template.zip"'})


@app.get('/api/files/list')
def list_files():
    """已上传材料列表（含用户指定的类别）"""
    out_dir = TOOL_DIR / 'documents' / 'uploads'
    idx = load_doc_index()
    items = []
    if out_dir.exists():
        for f in sorted(out_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.is_file() and f.name != '_index.json':
                items.append({'name': f.name, 'path': f'documents/uploads/{f.name}',
                              'size': f.stat().st_size,
                              'category': idx.get(f.name) or doc_type_of(f.name)})
    return {'items': items, 'categories': DOC_CATEGORIES}


@app.delete('/api/files/{name}')
def delete_file(name: str):
    target = TOOL_DIR / 'documents' / 'uploads' / Path(name).name  # 防路径穿越
    if not target.exists():
        raise HTTPException(404, '文件不存在')
    target.unlink()
    idx = load_doc_index()
    idx.pop(target.name, None)
    save_doc_index(idx)
    return {'ok': True}


@app.post('/api/files/upload')
async def upload_files(files: list[UploadFile] = File(...), categories: list[str] = Form(default=[])):
    """批量上传材料文件到 documents/uploads/，可随带与文件等长的类别列表，
    供 Excel/JSON 的材料列按文件名引用（类别优先取此处指定值）"""
    allowed = {'.pdf', '.png', '.jpg', '.jpeg'}
    out_dir = TOOL_DIR / 'documents' / 'uploads'
    out_dir.mkdir(parents=True, exist_ok=True)
    idx = load_doc_index()
    saved, rejected = [], []
    for i, f in enumerate(files):
        # 文件夹上传时浏览器会把相对路径（材料/证据/xx.pdf）放进 filename，只取纯文件名
        raw_name = fix_filename(f.filename or 'file').replace('\\', '/').rsplit('/', 1)[-1]
        name = re.sub(r'[^\w.\-一-鿿]', '_', raw_name)
        ext = os.path.splitext(name)[1].lower()
        category = categories[i] if i < len(categories) else ''
        if category not in DOC_CATEGORIES:
            category = doc_type_of(name)
        if ext not in allowed:
            rejected.append({'name': f.filename, 'reason': f'不支持的类型 {ext}（仅 pdf/png/jpg）'})
            continue
        data = await f.read()
        if len(data) > 20 * 1024 * 1024:
            rejected.append({'name': f.filename, 'reason': '超过 20MB 限制'})
            continue
        target = out_dir / name
        if target.exists():
            stem, e2 = os.path.splitext(name)
            name = f'{stem}_{datetime.now():%H%M%S}{e2}'
            target = out_dir / name
        target.write_bytes(data)
        idx[name] = category
        saved.append({'name': name, 'path': f'documents/uploads/{name}', 'size': len(data),
                      'category': category})
    save_doc_index(idx)
    return {'ok': not rejected, 'saved': saved, 'rejected': rejected}


@app.post('/api/cases/import')
async def import_cases(file: UploadFile = File(...), dry: bool = False):
    raw = await file.read()
    fname = fix_filename(file.filename or 'cases.json')
    is_xlsx = fname.lower().endswith(('.xlsx', '.xls'))
    if is_xlsx:
        data, parse_errors = parse_xlsx_cases(raw)
    else:
        try:
            data = json.loads(raw.decode('utf-8-sig'))
        except Exception as e:
            raise HTTPException(400, f'JSON 解析失败: {e}')
        parse_errors = []
    cases, errors = validate_cases(data)
    all_errors = parse_errors + errors
    if all_errors:
        return {'ok': False, 'errors': all_errors, 'cases': cases if is_xlsx else None}
    if dry:
        return {'ok': True, 'dry': True, 'cases': cases}

    safe = re.sub(r'[^\w.\-一-鿿]', '_', fname)
    saved = UPLOAD_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{safe}"
    if is_xlsx:
        # Excel 一律转成 JSON 后走统一入库链路
        saved = saved.with_suffix('.json')
        saved.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        saved.write_bytes(raw)

    proc = subprocess.run(
        [sys.executable, 'import_cases_to_db.py', '--data-file', str(saved)],
        cwd=str(TOOL_DIR), capture_output=True, text=True, timeout=120,
        encoding='utf-8', errors='replace')
    out = (proc.stdout or '') + (proc.stderr or '')
    imported = re.findall(r'\[新增\] (\S+) -> cases\.id=(\d+)', out)
    updated = re.findall(r'\[更新\] (\S+)', out)
    return {'ok': proc.returncode == 0, 'saved_as': saved.name,
            'imported': [{'case_no': n, 'id': int(i)} for n, i in imported],
            'updated': updated, 'log': out[-3000:]}


# ---------------- 立案执行 ----------------

class RunRequest(BaseModel):
    case_ids: list[int]


@app.post('/api/filing/run')
def start_run(body: RunRequest, admin: dict = Depends(current_admin)):
    if not admin.get('bound_court_user_id'):
        raise HTTPException(400, '请先在「账号管理」页绑定一个法院账号后再发起立案')
    # 取当前登录管理员绑定的法院账号（明文密码仅注入子进程环境变量，不落日志）
    with db() as conn, conn.cursor() as cur:
        cur.execute('SELECT username, password, is_active FROM system_users WHERE id=%s',
                    (admin['bound_court_user_id'],))
        acc = cur.fetchone()
    if not acc or not acc['is_active']:
        raise HTTPException(400, '绑定的法院账号已停用，请重新绑定')
    with db() as conn, conn.cursor() as cur:
        qmarks = ','.join(['%s'] * len(body.case_ids))
        cur.execute(f'SELECT id, case_no FROM cases WHERE id IN ({qmarks})', body.case_ids)
        found = cur.fetchall()
    if not found:
        raise HTTPException(400, '未找到所选案件')
    case_nos = [r['case_no'] for r in found]

    with runs_lock:
        for r in runs.values():
            if r['status'] == 'running':
                raise HTTPException(409, f"已有运行中的立案任务（{r['id']}），请先完成或取消")

    run_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
    log_path = RUN_LOG_DIR / f'{run_id}.log'
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    # 登录管理员绑定的法院账号优先于 .env / system_users 默认账号
    env['BEIJING_COURT_USERNAME'] = acc['username']
    env['BEIJING_COURT_PASSWORD'] = acc['password']
    logf = open(log_path, 'w', encoding='utf-8')
    proc = subprocess.Popen(
        [sys.executable, '-u', 'test_filing_flow.py', '--from-db',
         '--db-case-nos', ','.join(case_nos), '--visual'],
        cwd=str(TOOL_DIR), stdout=logf, stderr=subprocess.STDOUT, env=env)
    meta = {'id': run_id, 'case_nos': case_nos, 'pid': proc.pid,
            'started_at': datetime.now().isoformat(timespec='seconds'),
            'finished_at': None, 'status': 'running', 'returncode': None,
            'log': str(log_path),
            'admin': admin['username'], 'court_account': mask_account(acc['username'])}
    with runs_lock:
        runs[run_id] = meta
        save_runs_meta()

    def watch():
        rc = proc.wait()
        logf.close()
        with runs_lock:
            meta['status'] = 'success' if rc == 0 else 'failed'
            meta['returncode'] = rc
            meta['finished_at'] = datetime.now().isoformat(timespec='seconds')
            save_runs_meta()
        sync_case_status_from_report(log_path)

    threading.Thread(target=watch, daemon=True).start()
    return {'ok': True, 'run_id': run_id, 'case_nos': case_nos}


# 立案结果状态 → cases.status（STATUS_LABEL）
CASE_STATUS_MAP = {'已提交': 1, '待提交': 1, '已驳回': 2}


def sync_case_status_from_report(log_path: Path):
    """运行结束后读取最新进度报告，把逐案结果回写到 cases.status，让案件管理页同步"""
    try:
        text = log_path.read_text(encoding='utf-8', errors='replace')
        report_paths = re.findall(r'测试报告: (\S+?\.json)', text)
        if not report_paths:
            return
        rep = json.loads(Path(report_paths[-1]).read_text(encoding='utf-8'))
        results = rep.get('results', [])
        if not results:
            return
        with db() as conn, conn.cursor() as cur:
            for c in results:
                new_status = CASE_STATUS_MAP.get(c.get('status'))
                if new_status is None:
                    continue
                cur.execute('UPDATE cases SET status=%s WHERE case_no=%s',
                            (new_status, c.get('case_no')))
            conn.commit()
    except Exception as e:
        print(f'[warn] 回写案件状态失败: {e}')


@app.get('/api/filing/runs')
def list_runs():
    with runs_lock:
        items = sorted(runs.values(), key=lambda r: r['id'], reverse=True)
    # 注意不能 pop 原 dict（会顺手把内存里的 pid 删掉导致取消任务失败），返回拷贝
    return {'items': [{k: v for k, v in r.items() if k != 'pid'} for r in items[:50]]}


@app.get('/api/filing/runs/{run_id}')
def run_detail(run_id: str):
    r = runs.get(run_id)
    if not r:
        raise HTTPException(404, '运行记录不存在')
    out = {k: v for k, v in r.items() if k not in ('pid', 'log')}
    log_path = Path(r['log'])
    if not log_path.exists():
        return out
    text = log_path.read_text(encoding='utf-8', errors='replace')

    # 逐案结果：日志中每完成一案会写进度报告「测试报告: <path> progress_NofM.json」，
    # 报告 JSON 内含已完成的 results[]，比解析日志文本可靠；运行中也能实时看到进度
    completed = []
    report_paths = re.findall(r'测试报告: (\S+?\.json)', text)
    if report_paths:
        latest = Path(report_paths[-1])
        if latest.exists():
            try:
                rep = json.loads(latest.read_text(encoding='utf-8'))
                completed = rep.get('results', [])
            except Exception:
                pass
    # 正在处理的案件 = 已出现「--- [N] 测试案件 X ---」但尚未出现在报告 results 中
    done_nos = {c.get('case_no') for c in completed}
    started = re.findall(r'--- \[(\d+)\] 测试案件 (\S+) ---', text)
    current = None
    for _, no in started:
        if no not in done_nos:
            current = no
    out['cases'] = completed
    out['current_case'] = current
    out['total_cases'] = max(len(r.get('case_nos') or []), len(started))
    return out


@app.get('/api/filing/runs/{run_id}/log')
def run_log(run_id: str, offset: int = 0):
    r = runs.get(run_id)
    if not r:
        raise HTTPException(404, '运行记录不存在')
    log_path = Path(r['log'])
    if not log_path.exists():
        return {'offset': 0, 'text': '', 'status': r['status']}
    with open(log_path, 'rb') as f:
        f.seek(offset)
        chunk = f.read()
        new_offset = f.tell()
    return {'offset': new_offset, 'text': chunk.decode('utf-8', errors='replace'),
            'status': r['status']}


@app.post('/api/filing/runs/{run_id}/cancel')
def cancel_run(run_id: str):
    r = runs.get(run_id)
    if not r:
        raise HTTPException(404, '运行记录不存在')
    if r['status'] != 'running':
        return {'ok': False, 'message': '任务已结束'}
    try:
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(r['pid'])],
                       capture_output=True, timeout=15)
    except Exception as e:
        raise HTTPException(500, f'终止失败: {e}')
    with runs_lock:
        r['status'] = 'cancelled'
        r['finished_at'] = datetime.now().isoformat(timespec='seconds')
        save_runs_meta()
    return {'ok': True}


# ---------------- 保全申请执行 ----------------

def sync_preserve_status_from_report(log_path: Path):
    """保全运行结束后回写 preserve_cases.status"""
    try:
        text = log_path.read_text(encoding='utf-8', errors='replace')
        report_paths = re.findall(r'测试报告: (\S+?\.json)', text)
        if not report_paths:
            return
        rep = json.loads(Path(report_paths[-1]).read_text(encoding='utf-8'))
        results = rep.get('results', [])
        if not results:
            return
        with db() as conn, conn.cursor() as cur:
            for c in results:
                new_status = CASE_STATUS_MAP.get(c.get('status'))
                if new_status is None:
                    continue
                cur.execute('UPDATE preserve_cases SET status=%s WHERE case_no=%s',
                            (new_status, c.get('case_no')))
            conn.commit()
    except Exception as e:
        print(f'[warn] 回写保全案件状态失败: {e}')


@app.post('/api/preserve/run')
def start_preserve_run(body: RunRequest, admin: dict = Depends(current_admin)):
    if not admin.get('bound_court_user_id'):
        raise HTTPException(400, '请先在「账号管理」页绑定一个法院账号后再发起保全申请')
    with db() as conn, conn.cursor() as cur:
        cur.execute('SELECT username, password, is_active FROM system_users WHERE id=%s',
                    (admin['bound_court_user_id'],))
        acc = cur.fetchone()
    if not acc or not acc['is_active']:
        raise HTTPException(400, '绑定的法院账号已停用，请重新绑定')
    with db() as conn, conn.cursor() as cur:
        qmarks = ','.join(['%s'] * len(body.case_ids))
        cur.execute(f'SELECT id, case_no FROM preserve_cases WHERE id IN ({qmarks})', body.case_ids)
        found = cur.fetchall()
    if not found:
        raise HTTPException(400, '未找到所选保全案件')
    case_nos = [r['case_no'] for r in found]

    with runs_lock:
        for r in runs.values():
            if r['status'] == 'running':
                raise HTTPException(409, f"已有运行中的任务（{r['id']}），请先完成或取消")

    run_id = 'bq_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
    log_path = RUN_LOG_DIR / f'{run_id}.log'
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['BEIJING_COURT_USERNAME'] = acc['username']
    env['BEIJING_COURT_PASSWORD'] = acc['password']
    logf = open(log_path, 'w', encoding='utf-8')
    proc = subprocess.Popen(
        [sys.executable, '-u', 'preserve_filing_flow.py',
         '--db-case-nos', ','.join(case_nos)],
        cwd=str(TOOL_DIR), stdout=logf, stderr=subprocess.STDOUT, env=env)
    meta = {'id': run_id, 'case_nos': case_nos, 'pid': proc.pid, 'type': 'preserve',
            'started_at': datetime.now().isoformat(timespec='seconds'),
            'finished_at': None, 'status': 'running', 'returncode': None,
            'log': str(log_path),
            'admin': admin['username'], 'court_account': mask_account(acc['username'])}
    with runs_lock:
        runs[run_id] = meta
        save_runs_meta()

    def watch():
        rc = proc.wait()
        logf.close()
        with runs_lock:
            meta['status'] = 'success' if rc == 0 else 'failed'
            meta['returncode'] = rc
            meta['finished_at'] = datetime.now().isoformat(timespec='seconds')
            save_runs_meta()
        sync_preserve_status_from_report(log_path)

    threading.Thread(target=watch, daemon=True).start()
    return {'ok': True, 'run_id': run_id, 'case_nos': case_nos}


# ---------------- 生产模式：托管前端构建产物 ----------------
if DIST_DIR.exists():
    app.mount('/assets', StaticFiles(directory=DIST_DIR / 'assets'), name='assets')

    @app.get('/{full_path:path}')
    def spa(full_path: str):
        f = DIST_DIR / full_path
        if full_path and f.exists() and f.is_file():
            return FileResponse(f)
        return FileResponse(DIST_DIR / 'index.html')


if __name__ == '__main__':
    import uvicorn
    port = int(os.environ.get('API_PORT', '8100'))
    uvicorn.run(app, host='0.0.0.0', port=port, log_level='warning')
