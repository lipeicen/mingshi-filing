#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把案件 JSON 数据导入 MySQL（court_filing_civil），供 test_filing_flow.py --from-db 读取。

列名与既有库结构一致（applicant_* / respondent_* / agents 表 / case_files 表）。
重复导入同一 case_no 会更新原记录，不会插入重复案件，也不会影响库中其他案件。

用法：
    # 首次（或已有库缺列时）：建库建表/补齐缺失列 + 导入默认新测试数据
    python import_cases_to_db.py --init-schema

    # 指定数据文件导入
    python import_cases_to_db.py --data-file test_data/test_cases_new.json

    # 把 .env 里的法院账号同步到 system_users（可选）
    python import_cases_to_db.py --init-schema --sync-account

导入后运行：
    python test_filing_flow.py --from-db --visual
"""
import argparse
import json
import os
import sys

base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(base_dir, 'src'))

try:
    import pymysql
except ImportError:
    print('缺少依赖，请先执行: pip install pymysql')
    sys.exit(1)

from config import settings

SCHEMA_PATH = os.path.join(base_dir, 'db', 'schema.sql')
DEFAULT_DATA = os.path.join(base_dir, 'test_data', 'test_cases_new.json')

# 工具读取 cases 所需的最小列集（既有库缺列时由 --init-schema 自动 ALTER 补齐）
REQUIRED_CASE_COLUMNS = {
    'case_no': "VARCHAR(64) NOT NULL DEFAULT ''",
    'case_name': 'VARCHAR(255) NULL',
    'case_type': "VARCHAR(50) NOT NULL DEFAULT '民事案件'",
    'court_code': "VARCHAR(20) NOT NULL DEFAULT 'beijing'",
    'court_name': "VARCHAR(100) NOT NULL DEFAULT ''",
    'court_province': "VARCHAR(50) NOT NULL DEFAULT '北京'",
    'case_reason': "VARCHAR(200) NOT NULL DEFAULT ''",
    'claim': 'TEXT NULL',
    'facts': 'TEXT NULL',
    'claim_amount': 'DECIMAL(15,2) NOT NULL DEFAULT 0',
    'applicant_type': 'VARCHAR(64) NULL',
    'applicant_name': "VARCHAR(128) NOT NULL DEFAULT ''",
    'applicant_id': 'VARCHAR(64) NULL',
    'applicant_uscc': 'VARCHAR(50) NULL',
    'applicant_phone': 'VARCHAR(32) NULL',
    'applicant_address': 'TEXT NULL',
    'applicant_nature': "VARCHAR(50) NOT NULL DEFAULT '自然人'",
    'applicant_gender': 'VARCHAR(10) NULL',
    'applicant_birth': 'DATE NULL',
    'applicant_age': 'INT NULL',
    'applicant_legal_person': 'VARCHAR(64) NULL',
    'applicant_cert_type': 'VARCHAR(20) NULL',
    'applicant_cert_no': 'VARCHAR(64) NULL',
    'applicant_tel': 'VARCHAR(32) NULL',
    'applicant_reg_address': 'TEXT NULL',
    'respondent_name': "VARCHAR(128) NOT NULL DEFAULT ''",
    'respondent_id': 'VARCHAR(64) NULL',
    'respondent_uscc': 'VARCHAR(50) NULL',
    'respondent_phone': 'VARCHAR(32) NULL',
    'respondent_address': 'TEXT NULL',
    'respondent_nature': "VARCHAR(50) NOT NULL DEFAULT '自然人'",
    'respondent_gender': 'VARCHAR(10) NULL',
    'respondent_birth': 'DATE NULL',
    'respondent_age': 'INT NULL',
    'respondent_legal_person': 'VARCHAR(64) NULL',
    'respondent_cert_type': 'VARCHAR(20) NULL',
    'respondent_cert_no': 'VARCHAR(64) NULL',
    'respondent_tel': 'VARCHAR(32) NULL',
    'respondent_reg_address': 'TEXT NULL',
    'status': 'INT NOT NULL DEFAULT 0',
    'remark': 'TEXT NULL',
}

CASE_COLUMNS = list(REQUIRED_CASE_COLUMNS.keys())


def init_schema(conn, db_name):
    """执行 db/schema.sql 建库建表，并为既有表补齐缺失列。"""
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        sql = f.read()
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith('--')]
    statements = [s.strip() for s in '\n'.join(lines).split(';') if s.strip()]
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
        conn.select_db(db_name)
        # 既有 cases 表补齐缺失列（不动已有列和数据）
        cur.execute(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=%s AND TABLE_NAME='cases'", (db_name,))
        existing = {r[0] for r in cur.fetchall()}
        added = []
        for col, ddl in REQUIRED_CASE_COLUMNS.items():
            if col not in existing:
                cur.execute(f'ALTER TABLE cases ADD COLUMN {col} {ddl}')
                added.append(col)
    conn.commit()
    msg = f'，cases 表补齐缺失列: {", ".join(added)}' if added else '，cases 表列完整'
    print(f'[schema] 已执行 {len(statements)} 条 DDL{msg}')


def derive_id_fields(idcard):
    """从 18 位身份证号推导 出生日期/年龄/性别。非身份证号返回空。"""
    idcard = (idcard or '').strip()
    if len(idcard) != 18 or not idcard[:17].isdigit():
        return {'birth': None, 'age': None, 'gender': ''}
    try:
        from datetime import date
        birth = date(int(idcard[6:10]), int(idcard[10:12]), int(idcard[12:14]))
        today = date.today()
        age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
        gender = '男' if int(idcard[16]) % 2 == 1 else '女'
        return {'birth': birth.isoformat(), 'age': age, 'gender': gender}
    except ValueError:
        return {'birth': None, 'age': None, 'gender': ''}


def to_db_row(raw, status):
    """把 JSON 案件映射为 cases 表行（legacy 列名）。"""
    p = raw.get('plaintiff', {})
    d = raw.get('defendant', {})
    case_name = raw.get('case_name') or f"{p.get('name', '')}诉{d.get('name', '')}{raw.get('case_cause', '')}"
    p_nature = p.get('litigant_type', '自然人')
    d_nature = d.get('litigant_type', '自然人')
    # 自然人：从身份证号推导出生日期/年龄/性别
    p_derived = derive_id_fields(p.get('idcard', '')) if p_nature == '自然人' else {'birth': None, 'age': None, 'gender': ''}
    d_derived = derive_id_fields(d.get('idcard', '')) if d_nature == '自然人' else {'birth': None, 'age': None, 'gender': ''}
    return {
        'case_no': raw['case_no'],
        'case_name': case_name,
        'case_type': raw.get('case_type', '民事案件'),
        'court_code': raw.get('court_code', 'beijing'),
        'court_name': raw['court_name'],
        'court_province': raw.get('court_province', '北京'),
        'case_reason': raw.get('case_cause', ''),
        'claim': raw.get('claims', ''),
        'facts': raw.get('facts', ''),
        'claim_amount': float(raw.get('amount') or 0),
        'applicant_type': raw.get('applicant_type', ''),
        'applicant_name': p.get('name', ''),
        # 自然人证件号入 applicant_id；法人统一社会信用代码入 applicant_uscc
        'applicant_id': p.get('idcard', '') if p_nature == '自然人' else '',
        'applicant_uscc': p.get('idcard', '') if p_nature != '自然人' else '',
        'applicant_phone': p.get('phone', ''),
        'applicant_address': p.get('address', ''),
        'applicant_nature': p_nature,
        'applicant_gender': p_derived['gender'],
        'applicant_birth': p_derived['birth'],
        'applicant_age': p_derived['age'],
        'applicant_legal_person': p.get('legal_person', ''),
        'applicant_cert_type': '居民身份证' if p.get('legal_person_id') else '',
        'applicant_cert_no': p.get('legal_person_id', ''),
        'applicant_tel': p.get('legal_person_phone', ''),
        'applicant_reg_address': p.get('registered_address', ''),
        'respondent_name': d.get('name', ''),
        'respondent_id': d.get('idcard', '') if d_nature == '自然人' else '',
        'respondent_uscc': d.get('idcard', '') if d_nature != '自然人' else '',
        'respondent_phone': d.get('phone', ''),
        'respondent_address': d.get('address', ''),
        'respondent_nature': d_nature,
        'respondent_gender': d_derived['gender'],
        'respondent_birth': d_derived['birth'],
        'respondent_age': d_derived['age'],
        'respondent_legal_person': d.get('legal_person', ''),
        'respondent_cert_type': '居民身份证' if d.get('legal_person_id') else '',
        'respondent_cert_no': d.get('legal_person_id', ''),
        'respondent_tel': d.get('legal_person_phone', ''),
        'respondent_reg_address': d.get('registered_address', ''),
        'status': status,
        'remark': raw.get('remark', ''),
    }


def upsert_case(conn, row, documents, agents):
    """按 case_no 幂等写入 cases（存在即更新），并整体替换其 agents / case_files。"""
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM cases WHERE case_no=%s ORDER BY id LIMIT 1', (row['case_no'],))
        found = cur.fetchone()
        if found:
            case_id = found[0]
            sets = ', '.join(f'{c}=%s' for c in CASE_COLUMNS if c != 'case_no')
            cur.execute(f'UPDATE cases SET {sets} WHERE id=%s',
                        [row[c] for c in CASE_COLUMNS if c != 'case_no'] + [case_id])
        else:
            placeholders = ', '.join(['%s'] * len(CASE_COLUMNS))
            cur.execute(f'INSERT INTO cases ({", ".join(CASE_COLUMNS)}) VALUES ({placeholders})',
                        [row[c] for c in CASE_COLUMNS])
            case_id = cur.lastrowid

        cur.execute('DELETE FROM agents WHERE case_id=%s', (case_id,))
        for a in agents:
            a_gender = derive_id_fields(a.get('idcard', ''))['gender']
            cur.execute(
                'INSERT INTO agents (case_id, agent_type, agent_name, agent_gender, agent_cert_type, '
                'agent_cert_no, agent_phone, agent_license_no, agent_law_firm) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                (case_id, a.get('type', '执业律师'), a.get('name', ''), a_gender,
                 a.get('cert_type', '居民身份证'), a.get('idcard', ''),
                 a.get('phone', ''), a.get('license_no', ''), a.get('work_unit', '')),
            )

        cur.execute('DELETE FROM case_files WHERE case_id=%s', (case_id,))
        for i, doc in enumerate(documents):
            path = doc.get('path', '')
            if path and not os.path.isabs(path):
                path = os.path.abspath(os.path.join(base_dir, path))
            cur.execute(
                'INSERT INTO case_files (case_id, file_category, file_name, file_path, upload_status) '
                'VALUES (%s, %s, %s, %s, 0)',
                (case_id, doc.get('type', '其他材料'), doc.get('name', '材料'), path),
            )
    return case_id, bool(found)


def sync_account(conn):
    """把环境变量/.env 中的法院账号写入 system_users（幂等）。"""
    username = os.getenv('BEIJING_COURT_USERNAME', '')
    password = os.getenv('BEIJING_COURT_PASSWORD', '')
    if not username or not password:
        print('[account] 未检测到 BEIJING_COURT_USERNAME/PASSWORD 环境变量，跳过账号同步')
        return
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM system_users WHERE is_active=1 ORDER BY id LIMIT 1')
        row = cur.fetchone()
        if row:
            cur.execute('UPDATE system_users SET username=%s, password=%s WHERE id=%s',
                        (username, password, row[0]))
        else:
            cur.execute('INSERT INTO system_users (username, password, court_code, is_active) '
                        'VALUES (%s, %s, %s, 1)', (username, password, 'beijing'))
    conn.commit()
    print(f'[account] 已同步法院账号 {username[:3]}****{username[-4:]} 到 system_users')


def main():
    parser = argparse.ArgumentParser(description='把案件 JSON 导入 MySQL，供 --from-db 立案使用')
    parser.add_argument('--data-file', default=DEFAULT_DATA, help='案件 JSON 路径')
    parser.add_argument('--init-schema', action='store_true',
                        help='建库建表，并为既有 cases 表补齐缺失列')
    parser.add_argument('--sync-account', action='store_true',
                        help='把环境变量中的法院账号同步到 system_users')
    parser.add_argument('--status', type=int, default=0, help='导入后的 cases.status（0=待立案）')
    args = parser.parse_args()

    cfg = dict(settings.DB_CONFIG)
    db_name = cfg.get('database', 'court_filing_civil')
    cfg_without_db = {k: v for k, v in cfg.items() if k != 'database'}
    conn = pymysql.connect(**(cfg_without_db if args.init_schema else cfg))
    try:
        if args.init_schema:
            init_schema(conn, db_name)
        else:
            conn.select_db(db_name)
        if args.sync_account:
            sync_account(conn)

        with open(args.data_file, 'r', encoding='utf-8') as f:
            cases = json.load(f)
        print(f'[import] 读取 {len(cases)} 个案件: {args.data_file}')
        for raw in cases:
            row = to_db_row(raw, args.status)
            case_id, existed = upsert_case(conn, row, raw.get('documents', []), raw.get('agents', []))
            action = '更新' if existed else '新增'
            print(f"  ✓ [{action}] {row['case_no']} -> cases.id={case_id} "
                  f"({row['applicant_nature']}原告, {len(raw.get('agents', []))}个代理人, "
                  f"{len(raw.get('documents', []))}份材料, status={args.status})")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM cases WHERE status=0')
            pending = cur.fetchone()[0]
        print(f'[done] 导入完成，当前待立案案件 {pending} 条。可用 python test_filing_flow.py --from-db 运行')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
