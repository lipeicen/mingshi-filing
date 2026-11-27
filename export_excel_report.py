#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将法院自动立案工具的新测试数据与测试结果导出为 Excel 报告。

数据源：
  - extracted/test_data/test_cases_new.json       (测试案件数据)
  - extracted/results/new_data_test_results.json  (新数据测试结果)
输出：
  - 法院立案测试数据与结果报告.xlsx
"""
import json
import os
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_JSON = os.path.join(BASE, 'extracted', 'test_data', 'test_cases_new.json')
DATA_JSON2 = os.path.join(BASE, 'extracted', 'test_data', 'test_cases_db_e2e.json')
DATA_JSON3 = os.path.join(BASE, 'extracted', 'test_data', 'test_cases_provinces.json')
DATA_JSON4 = os.path.join(BASE, 'extracted', 'test_data', 'test_cases_provinces2.json')
RESULT_JSON = os.path.join(BASE, 'extracted', 'results', 'new_data_test_results.json')
OUT_XLSX = os.path.join(BASE, '法院立案测试数据与结果报告.xlsx')

ACCENT = '1F4E79'          # 深蓝
ACCENT_LIGHT = 'DCE6F1'    # 浅蓝
GREY = 'F2F2F2'
GREEN = 'C6EFCE'
GREEN_FONT = '006100'
RED = 'FFC7CE'
RED_FONT = '9C0006'

from openpyxl.styles import Side
thin_side = Side(style='thin', color='BFBFBF')
box = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

F_TITLE = Font(name='微软雅黑', size=16, bold=True, color=ACCENT)
F_H = Font(name='微软雅黑', size=10, bold=True, color='FFFFFF')
F_B = Font(name='微软雅黑', size=10)
F_BOLD = Font(name='微软雅黑', size=10, bold=True)
FILL_H = PatternFill('solid', fgColor=ACCENT)
FILL_ALT = PatternFill('solid', fgColor=GREY)
FILL_PASS = PatternFill('solid', fgColor=GREEN)
FILL_FAIL = PatternFill('solid', fgColor=RED)


def style_header(ws, row, ncols, start_col=2):
    for i in range(ncols):
        c = ws.cell(row=row, column=start_col + i)
        c.font = F_H
        c.fill = FILL_H
        c.alignment = Alignment(horizontal='center', vertical='center')
        c.border = box


def put_title(ws, row, text, ncols, start_col=2):
    ws.merge_cells(start_row=row, start_column=start_col, end_row=row, end_column=start_col + ncols - 1)
    c = ws.cell(row=row, column=start_col, value=text)
    c.font = F_TITLE
    c.alignment = Alignment(horizontal='left', vertical='center')
    ws.row_dimensions[row].height = 28


def write_table(ws, start_row, headers, rows, widths, start_col=2, status_col=None):
    """写一个带表头的表格；status_col(1-based 相对 headers) 为状态列时按 通过/失败 着色"""
    for j, h in enumerate(headers):
        ws.cell(row=start_row, column=start_col + j, value=h)
    style_header(ws, start_row, len(headers), start_col)
    for i, row in enumerate(rows):
        r = start_row + 1 + i
        for j, v in enumerate(row):
            c = ws.cell(row=r, column=start_col + j, value=v)
            c.font = F_B
            c.border = box
            c.alignment = Alignment(vertical='center', wrap_text=isinstance(v, str) and len(v) > 25)
            if i % 2 == 1:
                c.fill = FILL_ALT
        if status_col is not None:
            sc = ws.cell(row=r, column=start_col + status_col - 1)
            if sc.value == '通过':
                sc.fill = FILL_PASS
                sc.font = Font(name='微软雅黑', size=10, bold=True, color=GREEN_FONT)
            elif sc.value == '失败':
                sc.fill = FILL_FAIL
                sc.font = Font(name='微软雅黑', size=10, bold=True, color=RED_FONT)
            sc.alignment = Alignment(horizontal='center', vertical='center')
    for j, w in enumerate(widths):
        ws.column_dimensions[get_column_letter(start_col + j)].width = w
    return start_row + 1 + len(rows)


def main():
    cases = []
    for data_file in (DATA_JSON, DATA_JSON2, DATA_JSON3, DATA_JSON4):
        if os.path.exists(data_file):
            with open(data_file, 'r', encoding='utf-8') as f:
                cases.extend(json.load(f))
    report = None
    if os.path.exists(RESULT_JSON):
        with open(RESULT_JSON, 'r', encoding='utf-8') as f:
            report = json.load(f)

    wb = Workbook()

    # ============ Sheet 1: 概览 ============
    ws = wb.active
    ws.title = '概览'
    ws.sheet_view.showGridLines = False
    put_title(ws, 2, '法院自动立案工具 — 新数据测试报告', 6)
    ws.cell(row=3, column=2, value=f'生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}').font = F_B

    metrics = [
        ('测试案件总数', len(cases)),
        ('涉及案由数', len({c['case_cause'] for c in cases})),
        ('涉及法院数', len({c['court_name'] for c in cases})),
        ('标的金额合计(元)', sum(c['amount'] for c in cases)),
        ('材料文件总数', sum(len(c['documents']) for c in cases)),
        ('代理人总数', sum(len(c.get('agents', [])) for c in cases)),
    ]
    if report:
        metrics.append(('测试通过', report.get('passed', 0)))
        metrics.append(('测试失败', report.get('failed', 0)))
    r = 5
    ws.cell(row=r, column=2, value='关键指标').font = F_BOLD
    r += 1
    for i, (k, v) in enumerate(metrics):
        ck = ws.cell(row=r + i, column=2, value=k)
        cv = ws.cell(row=r + i, column=3, value=v)
        ck.font = F_B
        ck.border = box
        cv.font = F_BOLD
        cv.border = box
        if isinstance(v, float):
            cv.number_format = '#,##0.00'
        if i % 2 == 1:
            ck.fill = FILL_ALT
            cv.fill = FILL_ALT
    ws.column_dimensions['B'].width = 22
    ws.column_dimensions['C'].width = 18

    r2 = r + len(metrics) + 2
    ws.cell(row=r2, column=2, value='工作表索引').font = F_BOLD
    for i, name in enumerate(['概览', '案件数据', '当事人明细', '材料清单', '测试结果', '校验明细', '真实网站验证']):
        ws.cell(row=r2 + 1 + i, column=2, value=f'{i + 1}. {name}').font = F_B

    # ============ Sheet 2: 案件数据 ============
    ws = wb.create_sheet('案件数据')
    ws.sheet_view.showGridLines = False
    put_title(ws, 2, '测试案件数据（test_cases_new.json + test_cases_db_e2e.json）', 9)
    headers = ['案件编号', '案件类型', '受理法院', '案由', '标的金额(元)', '诉讼请求', '事实与理由', '原告', '被告']
    rows = [[c['case_no'], c['case_type'], c['court_name'], c['case_cause'], c['amount'],
             c['claims'], c['facts'], c['plaintiff']['name'], c['defendant']['name']] for c in cases]
    write_table(ws, 4, headers, rows, [20, 12, 24, 22, 14, 45, 50, 18, 18])
    for row in ws.iter_rows(min_row=5, min_col=6, max_col=6):
        for c in row:
            c.number_format = '#,##0.00'

    # ============ Sheet 3: 当事人明细 ============
    ws = wb.create_sheet('当事人明细')
    ws.sheet_view.showGridLines = False
    put_title(ws, 2, '当事人与代理人明细', 11)
    headers = ['案件编号', '角色', '名称/姓名', '当事人类型', '证件号码', '联系电话', '地址/注册地', '法定代表人', '代理人类型', '执业证号', '被代理人']
    rows = []
    for c in cases:
        for role, key in (('原告', 'plaintiff'), ('被告', 'defendant')):
            p = c[key]
            rows.append([c['case_no'], role, p['name'], p.get('litigant_type', '自然人'), p['idcard'],
                         p['phone'], p.get('registered_address') or p.get('address', ''),
                         p.get('legal_person', ''), '', '', ''])
        for a in c.get('agents', []):
            rows.append([c['case_no'], '代理人', a['name'], '自然人', a['idcard'], a['phone'],
                         a.get('work_unit', ''), '', a.get('type', ''), a.get('license_no', ''),
                         (a.get('principals') or [''])[0]])
    write_table(ws, 4, headers, rows, [20, 8, 24, 12, 22, 14, 30, 12, 12, 20, 24])

    # ============ Sheet 4: 材料清单 ============
    ws = wb.create_sheet('材料清单')
    ws.sheet_view.showGridLines = False
    put_title(ws, 2, '诉讼材料清单', 5)
    headers = ['案件编号', '材料名称', '材料类型', '文件路径', '文件存在']
    rows = []
    for c in cases:
        for d in c['documents']:
            p = d['path']
            full = p if os.path.isabs(p) else os.path.join(BASE, 'extracted', p)
            rows.append([c['case_no'], d['name'], d['type'], p, '是' if os.path.exists(full) else '否'])
    write_table(ws, 4, headers, rows, [20, 22, 16, 36, 10])

    # ============ Sheet 5/6: 测试结果 + 校验明细 ============
    ws = wb.create_sheet('测试结果')
    ws.sheet_view.showGridLines = False
    ws2 = wb.create_sheet('校验明细')
    ws2.sheet_view.showGridLines = False

    if report:
        put_title(ws, 2, f'新数据测试结果（{report.get("time", "")[:19]}）', 9)
        headers = ['案件编号', '案由', '受理法院', '标的金额(元)', '数据校验', '案由链路传递', '案由选中', '步骤推进', '总结果']
        rows = []
        detail_rows = []
        for r in report['results']:
            checks = {c['name']: c for c in r.get('flow_checks', [])}
            def chk(name):
                c = checks.get(name)
                return '通过' if (c and c['pass']) else ('失败' if c else '未执行')
            rows.append([
                r['case_no'], r['case_cause'], r['court_name'], r['amount'],
                '通过' if r['data_check']['pass'] else '失败',
                chk('案由经 CaseInfo 链路传递'),
                chk('案由选择器选中本案案由'),
                chk('下一步进入上传诉讼材料'),
                r['status'],
            ])
            for e in r['data_check'].get('errors', []):
                detail_rows.append([r['case_no'], '数据校验', '失败', e])
            for c in r.get('flow_checks', []):
                detail_rows.append([r['case_no'], c['name'],
                                    '通过' if c['pass'] else '失败',
                                    f"期望: {c.get('expected', '')} | 实际: {c.get('actual', '')}"])
        end = write_table(ws, 4, headers, rows, [20, 24, 24, 14, 10, 14, 10, 12, 10], status_col=9)
        # 各校验列也着色
        for i in range(len(rows)):
            for col in (6, 7, 8, 9):
                cell = ws.cell(row=5 + i, column=col)
                if cell.value == '通过':
                    cell.fill = FILL_PASS
                    cell.font = Font(name='微软雅黑', size=10, color=GREEN_FONT)
                elif cell.value == '失败':
                    cell.fill = FILL_FAIL
                    cell.font = Font(name='微软雅黑', size=10, color=RED_FONT)
                cell.alignment = Alignment(horizontal='center', vertical='center')
        for row in ws.iter_rows(min_row=5, min_col=5, max_col=5):
            for c in row:
                c.number_format = '#,##0.00'

        put_title(ws2, 2, '逐项校验明细', 4)
        write_table(ws2, 4, ['案件编号', '校验项', '结果', '说明'], detail_rows, [20, 26, 10, 70], status_col=3)
    else:
        put_title(ws, 2, '测试结果（未运行）', 4)
        ws.cell(row=4, column=2, value='未找到测试结果文件 results/new_data_test_results.json，请先运行 tests/test_new_data_causes.py').font = F_B
        put_title(ws2, 2, '逐项校验明细（未运行）', 4)

    # ============ Sheet 7: 真实网站验证 ============
    import glob as _glob
    reports = sorted(_glob.glob(os.path.join(BASE, 'extracted', 'results', 'test_filing_report_2*.json')))
    ws = wb.create_sheet('真实网站验证')
    ws.sheet_view.showGridLines = False
    real_rows = []
    real_time = ''
    if reports:
        # 合并所有正式报告（跳过 *_progress_ 中间文件），按案件编号去重，保留最新一次运行
        finals = [p for p in reports if '_progress_' not in os.path.basename(p)]
        by_case = {}
        for path in finals:
            with open(path, 'r', encoding='utf-8') as f:
                real = json.load(f)
            rt = (real.get('time') or '')[:19]
            if rt > real_time:
                real_time = rt
            for r in real.get('results', []):
                by_case[r.get('case_no', '')] = r  # 文件按时间排序，后者覆盖前者
        for case_no in sorted(by_case):
            r = by_case[case_no]
            real_rows.append([
                r.get('case_no', ''), r.get('court_name', ''), r.get('case_cause', ''),
                r.get('amount', 0), r.get('parties_count', 0), r.get('documents_count', 0),
                r.get('status', ''), r.get('message', ''), r.get('duration_seconds', 0),
            ])
    put_title(ws, 2, f'真实网站端到端验证（zxfw.court.gov.cn，DRY RUN）{real_time}', 9)
    if real_rows:
        write_table(ws, 4,
                    ['案件编号', '受理法院', '案由', '标的金额(元)', '当事人数', '材料数', '状态', '说明', '耗时(秒)'],
                    real_rows, [20, 24, 22, 14, 10, 10, 10, 30, 10], status_col=7)
        for row in ws.iter_rows(min_row=5, min_col=5, max_col=5):
            for c in row:
                c.number_format = '#,##0.00'
        ws.cell(row=6 + len(real_rows), column=2,
                value='说明：DRY RUN 模式仅走到「预览和提交」页，未真实提交案件；预览页原告/被告/代理人信息均已核对完整。').font = F_B
    else:
        ws.cell(row=4, column=2, value='尚无真实网站运行记录（results/test_filing_report_*.json）').font = F_B

    wb.save(OUT_XLSX)
    print(f'Excel 报告已生成: {OUT_XLSX}')
    print(f'案件数: {len(cases)}, 结果: {"已包含" if report else "缺失"}')


if __name__ == '__main__':
    main()
