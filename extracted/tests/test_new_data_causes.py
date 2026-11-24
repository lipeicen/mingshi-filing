#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新测试数据(test_cases_new.json)全链路验证：

1) 数据层：逐案校验字段完整性、18 位身份证号校验位、材料文件存在性；
2) 构建层：调用 test_filing_flow.build_case_info 走真实数据构建链路，
   验证 case_cause 经 CaseInfo.to_dict() 后仍能传到 case_data['case_reason']
   （修复前该字段在数据链路中丢失，所有案件都会回退为默认案由「买卖合同纠纷」）；
3) 流程层：在 mock_flow.html 中调用 BeijingCourtAdapter._select_case_cause，
   验证选中案由与本案案由一致，且点「下一步」后进入「上传诉讼材料」步骤。

结果写入 results/new_data_test_results.json，供 Excel 报告使用。
"""
import os
import sys
import json
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)           # 让 test_filing_flow 可导入
sys.path.insert(0, os.path.join(BASE_DIR, 'src'))

from test_filing_flow import build_case_info  # noqa: E402
from adapters.beijing_court import BeijingCourtAdapter  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

DATA_PATH = os.path.join(BASE_DIR, 'test_data', 'test_cases_new.json')
MOCK_HTML = 'file://' + os.path.join(BASE_DIR, 'tests', 'mock_flow.html')
RESULT_PATH = os.path.join(BASE_DIR, 'results', 'new_data_test_results.json')

WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
CODES = '10X98765432'


def valid_idcard(no: str) -> bool:
    """校验 18 位身份证号校验位（统一社会信用代码等非法身份证直接跳过）"""
    if len(no) != 18 or not no[:17].isdigit():
        return False
    return CODES[sum(int(d) * w for d, w in zip(no[:17], WEIGHTS)) % 11] == no[17].upper()


def active_step(page):
    return page.evaluate("""() => {
        const on = document.querySelector('.uni-steps__row-title.on');
        return on ? on.innerText.trim() : '';
    }""")


def selected_cause(page):
    return page.evaluate("""() => {
        const area = document.querySelector('.uni-data-tree .selected-area');
        return {
            text: (area.innerText || '').trim(),
            isPlaceholder: area.classList.contains('placeholder')
        };
    }""")


def check_case_data(raw):
    """数据层校验，返回 (ok, errors)"""
    errors = []
    for key in ('case_no', 'case_type', 'court_name', 'case_cause', 'claims', 'facts'):
        if not raw.get(key):
            errors.append(f'缺少字段: {key}')
    if not isinstance(raw.get('amount'), (int, float)) or raw['amount'] <= 0:
        errors.append('标的金额必须为正数')
    for role in ('plaintiff', 'defendant'):
        p = raw.get(role) or {}
        for key in ('name', 'idcard', 'phone', 'address'):
            if not p.get(key):
                errors.append(f'{role} 缺少字段: {key}')
        # 自然人身份证必须过校验位；法人使用统一社会信用代码，不校验
        if p.get('litigant_type', '自然人') == '自然人':
            if not valid_idcard(p.get('idcard', '')):
                errors.append(f'{role} 身份证校验位不合法: {p.get("idcard")}')
        else:
            for key in ('legal_person', 'legal_person_id', 'registered_address', 'org_type'):
                if not p.get(key):
                    errors.append(f'{role}(法人) 缺少字段: {key}')
            if not valid_idcard(p.get('legal_person_id', '')):
                errors.append(f'{role} 法定代表人身份证校验位不合法')
    for a in raw.get('agents', []):
        for key in ('name', 'idcard', 'phone', 'type', 'license_no', 'work_unit'):
            if not a.get(key):
                errors.append(f'代理人缺少字段: {key}')
        # 代理人身份证同样会被法院端校验，必须通过校验位
        if a.get('idcard') and not valid_idcard(a['idcard']):
            errors.append(f'代理人身份证校验位不合法: {a.get("idcard")}')
        if not a.get('principals'):
            errors.append('代理人缺少被代理人 principals')
        elif a['principals'][0] != raw['plaintiff']['name']:
            errors.append(f"被代理人 {a['principals'][0]} 与原告 {raw['plaintiff']['name']} 不一致")
    for d in raw.get('documents', []):
        p = d.get('path', '')
        full = p if os.path.isabs(p) else os.path.join(BASE_DIR, p)
        if not os.path.exists(full):
            errors.append(f'材料文件不存在: {p}')
    return (not errors), errors


def run_flow_for_case(browser, raw, screenshot_dir=None):
    """流程层：构建 CaseInfo -> _select_case_cause -> 下一步"""
    start = time.time()
    detail = {'checks': []}

    # 构建层：走真实 build_case_info 链路
    case_info = build_case_info(raw)
    case_data = case_info.to_dict()
    expected_cause = raw['case_cause']

    ok_build = case_data.get('case_reason') == expected_cause
    detail['checks'].append({
        'name': '案由经 CaseInfo 链路传递',
        'pass': ok_build,
        'expected': expected_cause,
        'actual': case_data.get('case_reason', ''),
    })

    page = browser.new_page()
    page.on('dialog', lambda d: d.dismiss())
    case_no = raw['case_no']

    def shot(name):
        if screenshot_dir:
            try:
                path = os.path.join(screenshot_dir, f'{case_no}_{name}.png')
                page.screenshot(path=path, timeout=5000)
                detail.setdefault('screenshots', []).append(path)
            except Exception:
                pass

    try:
        page.goto(MOCK_HTML)
        page.wait_for_timeout(400)
        # 切到案由步骤（前置步骤由 navigate_to_filing/fill_case_form 完成，不在本测试范围）。
        # 必须调用 mock 的 gotoStep，使底部「下一步」按钮指向 page-upload
        page.evaluate("() => gotoStep('page-cause')")
        page.wait_for_timeout(300)
        shot('01_案由页')

        adapter = BeijingCourtAdapter()
        # 可视化模式下先打开弹层截一张，再让正式流程重新走完整选择
        if screenshot_dir:
            page.evaluate("""() => {
                const el = document.querySelector('.uni-data-tree .uni-data-tree-input .input-value');
                if (el) el.click();
            }""")
            page.wait_for_timeout(500)
            shot('02_案由弹层')
            page.evaluate("""() => {
                const d = document.querySelector('.uni-data-tree-dialog');
                if (d) d.querySelector('.dialog-close').click();
            }""")
            page.wait_for_timeout(300)

        adapter._select_case_cause(page, case_data)
        page.wait_for_timeout(800)
        shot('03_案由已选中')

        st = selected_cause(page)
        ok_cause = (st['text'] == expected_cause) and not st['isPlaceholder']
        detail['checks'].append({
            'name': '案由选择器选中本案案由',
            'pass': ok_build and ok_cause,
            'expected': expected_cause,
            'actual': st['text'],
        })

        step = active_step(page)
        ok_step = step == '上传诉讼材料'
        detail['checks'].append({
            'name': '下一步进入上传诉讼材料',
            'pass': ok_step,
            'expected': '上传诉讼材料',
            'actual': step,
        })
        shot('04_上传材料页')
    finally:
        page.close()

    detail['duration_seconds'] = round(time.time() - start, 1)
    return detail


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--visual', action='store_true', help='可视化模式：有头浏览器并逐步截图')
    parser.add_argument('--screenshot-dir', default=os.path.join(BASE_DIR, 'screenshots', 'visual_new_data'))
    args = parser.parse_args()

    screenshot_dir = None
    if args.visual:
        screenshot_dir = args.screenshot_dir
        os.makedirs(screenshot_dir, exist_ok=True)
        print(f'可视化模式，截图保存到: {screenshot_dir}')

    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        cases = json.load(f)
    print(f'加载新测试案件 {len(cases)} 个: {[c["case_no"] for c in cases]}')

    os.makedirs(os.path.dirname(RESULT_PATH), exist_ok=True)
    report = {
        'time': datetime.now().isoformat(),
        'data_file': os.path.basename(DATA_PATH),
        'total': len(cases),
        'results': [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.visual)
        for raw in cases:
            res = {
                'case_no': raw['case_no'],
                'case_cause': raw['case_cause'],
                'court_name': raw['court_name'],
                'amount': raw['amount'],
                'plaintiff': raw['plaintiff']['name'],
                'defendant': raw['defendant']['name'],
            }
            ok_data, errors = check_case_data(raw)
            res['data_check'] = {'pass': ok_data, 'errors': errors}
            try:
                flow = run_flow_for_case(browser, raw, screenshot_dir=screenshot_dir)
                res['flow_checks'] = flow['checks']
                res['duration_seconds'] = flow['duration_seconds']
                if flow.get('screenshots'):
                    res['screenshots'] = flow['screenshots']
                flow_ok = all(c['pass'] for c in flow['checks'])
            except Exception as e:
                res['flow_checks'] = [{'name': '流程执行', 'pass': False, 'expected': '', 'actual': str(e)}]
                flow_ok = False
            res['status'] = '通过' if (ok_data and flow_ok) else '失败'
            report['results'].append(res)
            print(f"[{res['status']}] {res['case_no']} 案由={res['case_cause']}")
            for err in errors:
                print(f'    数据错误: {err}')
            for c in res.get('flow_checks', []):
                mark = 'PASS' if c['pass'] else 'FAIL'
                print(f"    {mark}: {c['name']} (期望={c['expected']!r} 实际={c['actual']!r})")
        browser.close()

    report['passed'] = sum(1 for r in report['results'] if r['status'] == '通过')
    report['failed'] = report['total'] - report['passed']
    with open(RESULT_PATH, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'\n结果: {report["passed"]}/{report["total"]} 通过, 报告: {RESULT_PATH}')
    if report['failed']:
        sys.exit(1)
    print('ALL NEW DATA TESTS PASSED')


if __name__ == '__main__':
    main()
