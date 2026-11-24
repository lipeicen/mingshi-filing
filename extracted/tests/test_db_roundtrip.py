#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库链路离线验证（无需 MySQL）：
用 import_cases_to_db.to_db_row 生成 cases 表行（legacy 列名）+ agents/case_files
表行 → 伪造 pymysql 游标返回 → 走真实 load_cases_from_db → 断言还原出的案件
字典与原始 JSON 一致。同时验证 build_case_info 能消费 DB 还原的数据。
"""
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import import_cases_to_db as imp
import test_filing_flow as flow


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        s = ' '.join(sql.split()).lower()
        if s.startswith('select') and ' from cases' in s:
            rows = self._conn.case_rows
            params = list(params or [])
            limit = params[-1] if params else 10
            if 'case_no in' in s:
                nos = set(params[:-1])
                rows = [r for r in rows if r.get('case_no') in nos]
            self._rows = [dict(r) for r in rows[:limit]]
        elif s.startswith('select') and 'from case_files' in s:
            ids = set(params or [])
            self._rows = [dict(r) for r in self._conn.file_rows if r['case_id'] in ids]
        elif s.startswith('select') and 'from agents' in s:
            ids = set(params or [])
            self._rows = [dict(r) for r in self._conn.agent_rows if r['case_id'] in ids]
        else:
            self._rows = []
        return len(self._rows)

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, case_rows, file_rows, agent_rows):
        self.case_rows = case_rows
        self.file_rows = file_rows
        self.agent_rows = agent_rows

    def cursor(self, *a, **kw):
        return FakeCursor(self)

    def close(self):
        pass


def build_fake_db(raw_cases):
    """模拟 import 后的 cases / case_files / agents 表内容。"""
    case_rows, file_rows, agent_rows = [], [], []
    for i, raw in enumerate(raw_cases, 1):
        row = imp.to_db_row(raw, status=0)
        row['id'] = i
        case_rows.append(row)
        for doc in raw.get('documents', []):
            path = doc.get('path', '')
            if path and not os.path.isabs(path):
                path = os.path.abspath(os.path.join(BASE_DIR, path))
            file_rows.append({
                'case_id': i,
                'file_category': doc.get('type', '其他材料'),
                'file_name': doc.get('name', '材料'),
                'file_path': path,
            })
        for a in raw.get('agents', []):
            agent_rows.append({
                'case_id': i,
                'agent_type': a.get('type', '执业律师'),
                'agent_name': a.get('name', ''),
                'agent_cert_type': a.get('cert_type', '居民身份证'),
                'agent_cert_no': a.get('idcard', ''),
                'agent_phone': a.get('phone', ''),
                'agent_license_no': a.get('license_no', ''),
                'agent_law_firm': a.get('work_unit', ''),
            })
    return FakeConn(case_rows, file_rows, agent_rows)


def main():
    # 身份证号推导字段验证
    d = imp.derive_id_fields('110108198811220110')
    from datetime import date
    expect_age = date.today().year - 1988 - ((date.today().month, date.today().day) < (11, 22))
    assert d == {'birth': '1988-11-22', 'age': expect_age, 'gender': '男'}, f'身份证推导错误: {d}'
    assert imp.derive_id_fields('91110105MA01XY7K3B') == {'birth': None, 'age': None, 'gender': ''}
    print(f'OK: 身份证推导正确（110108198811220110 -> 1988-11-22, {expect_age}岁, 男；统一社会信用代码不推导）')

    with open(os.path.join(BASE_DIR, 'test_data', 'test_cases_new.json'), encoding='utf-8') as f:
        raw_cases = json.load(f)

    conn = build_fake_db(raw_cases)
    flow.pymysql = type('FakePymysql', (), {
        'connect': staticmethod(lambda **kw: conn),
        'cursors': type('c', (), {'DictCursor': object}),
    })()

    loaded = flow.load_cases_from_db(limit=10)
    assert len(loaded) == len(raw_cases), f'案件数不一致: {len(loaded)} vs {len(raw_cases)}'

    errors = []
    for raw, db_case in zip(raw_cases, loaded):
        tag = raw['case_no']
        checks = [
            ('案由', db_case['case_cause'], raw['case_cause']),
            ('法院', db_case['court_name'], raw['court_name']),
            ('金额', float(db_case['amount']), float(raw['amount'])),
            ('原告名', db_case['plaintiff']['name'], raw['plaintiff']['name']),
            ('原告证件', db_case['plaintiff']['idcard'], raw['plaintiff']['idcard']),
            ('原告类型', db_case['plaintiff']['litigant_type'], raw['plaintiff'].get('litigant_type', '自然人')),
            ('被告名', db_case['defendant']['name'], raw['defendant']['name']),
            ('被告证件', db_case['defendant']['idcard'], raw['defendant']['idcard']),
            ('材料数', len(db_case['documents']), len(raw['documents'])),
            ('代理人数', len(db_case['agents']), len(raw.get('agents', []))),
        ]
        if raw['plaintiff'].get('litigant_type') == '法人':
            checks += [
                ('法定代表人', db_case['plaintiff']['legal_person'], raw['plaintiff']['legal_person']),
                ('法代证件号', db_case['plaintiff']['legal_person_id'], raw['plaintiff'].get('legal_person_id', '')),
                ('注册地', db_case['plaintiff']['registered_address'], raw['plaintiff'].get('registered_address', '')),
            ]
        if raw.get('agents'):
            checks += [
                ('代理人姓名', db_case['agents'][0]['name'], raw['agents'][0]['name']),
                ('代理人证件', db_case['agents'][0]['idcard'], raw['agents'][0]['idcard']),
                ('代理人执业证号', db_case['agents'][0]['license_no'], raw['agents'][0]['license_no']),
                ('代理人单位', db_case['agents'][0]['work_unit'], raw['agents'][0]['work_unit']),
                ('被代理人', db_case['agents'][0]['principals'][0], raw['plaintiff']['name']),
            ]
        for label, got, want in checks:
            if got != want:
                errors.append(f'{tag} [{label}] 期望 {want!r} 实际 {got!r}')

        # 材料路径必须真实存在（load 时 os.path.exists 过滤）
        missing = [d['path'] for d in db_case['documents'] if not os.path.exists(d['path'])]
        if missing:
            errors.append(f'{tag} 材料路径不存在: {missing}')

        # build_case_info 能消费 DB 还原的数据
        info = flow.build_case_info(db_case)
        assert info.case_cause == raw['case_cause'], f'{tag} 案由传递失败'
        agent_parties = [p for p in info.parties if p.party_type == '代理人']
        assert len(agent_parties) == len(raw.get('agents', [])), f'{tag} 代理人未传入 Party'
        if raw.get('agents'):
            assert agent_parties[0].represented_party == raw['plaintiff']['name'], f'{tag} 被代理人错误'

    if errors:
        print('FAILED:')
        for e in errors:
            print('  -', e)
        sys.exit(1)
    print(f'OK: {len(loaded)}/{len(raw_cases)} 个案件 DB 往返映射全部一致，build_case_info 链路通过')
    for c in loaded:
        lt = c['plaintiff']['litigant_type']
        print(f"  ✓ {c['case_no']}: {c['case_cause']} | 原告({lt}) {c['plaintiff']['name']} | "
              f"代理人 {len(c['agents'])} | 材料 {len(c['documents'])}")


if __name__ == '__main__':
    main()
