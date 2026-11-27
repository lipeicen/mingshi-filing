# -*- coding: utf-8 -*-
"""一次性探测：担保信息弹窗的担保方式选项及各方式的必填字段
复用 preserve_filing_flow 走到担保步骤，只探测不提交。
输出 extracted/results/probe_guarantee_types.json
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preserve_filing_flow as m
from playwright.sync_api import sync_playwright

OUT = m.BASE_DIR / 'results' / 'probe_guarantee_types.json'

DUMP_JS = """() => {
    const dlg = [...document.querySelectorAll('.el-dialog')].find(d => d.offsetParent);
    if (!dlg) return null;
    return [...dlg.querySelectorAll('.el-form-item')].map(item => ({
        label: (item.querySelector('.el-form-item__label')?.textContent || '').replace(/[*\\s]/g, ''),
        required: item.className.includes('is-required'),
        hasSelect: !!item.querySelector('.el-select'),
        inputs: [...item.querySelectorAll('input, textarea')].map(i => ({
            type: i.type, placeholder: i.placeholder || '', readonly: i.readOnly,
        })),
    })).filter(x => x.label);
}"""

OPEN_DD_JS = """(ph) => {
    const dlg = [...document.querySelectorAll('.el-dialog')].find(d => d.offsetParent);
    if (!dlg) return 'no-dialog';
    const input = [...dlg.querySelectorAll('input')].find(i => i.placeholder === ph);
    if (!input) return 'no-input';
    input.click();
    return 'ok';
}"""

READ_OPTIONS_JS = """() => {
    const dd = [...document.querySelectorAll('.el-select-dropdown')].find(d => (d.getBoundingClientRect().width > 0 && getComputedStyle(d).display !== 'none'));
    if (!dd) return [];
    return [...dd.querySelectorAll('.el-select-dropdown__item')].map(li => li.textContent.trim()).filter(t => t);
}"""

CLICK_OPTION_JS = """(txt) => {
    const dd = [...document.querySelectorAll('.el-select-dropdown')].find(d => (d.getBoundingClientRect().width > 0 && getComputedStyle(d).display !== 'none'));
    if (!dd) return 'no-dropdown';
    const item = [...dd.querySelectorAll('.el-select-dropdown__item')].find(li => li.textContent.trim() === txt);
    if (!item) return 'no-item';
    item.click();
    return 'ok';
}"""


def main():
    m.load_case_data('保全TEST-202611-01')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=m.HEADLESS)
        ctx = browser.new_context(viewport={'width': 1400, 'height': 900})
        page = ctx.new_page()
        if not m.auto_login(page):
            print('登录失败'); return
        page1 = m.create_preservation(page)
        time.sleep(2)
        print('添加申请人/被申请人/财产线索（为进入担保步骤）...')
        m.add_applicant(page1)
        m.add_respondent(page1)
        m.add_property(page1)

        # 点击下一步进入担保步骤
        clicked = page1.evaluate("() => { const btns = document.querySelectorAll('button, uni-button'); for(let btn of btns) { if(btn.textContent && btn.textContent.includes('下一步') && btn.offsetParent !== null) { btn.click(); return true; } } return false; }")
        print('下一步:', clicked)
        time.sleep(2)

        # 点击添加担保
        res = page1.evaluate("""() => {
            const spans = document.querySelectorAll('span, button');
            for(let s of spans) { if(s.textContent.trim() === '添加' && s.offsetParent !== null) { s.click(); return 'clicked'; } }
            return 'not found';
        }""")
        print('添加担保:', res)
        time.sleep(2)

        # 枚举担保方式选项
        st = page1.evaluate(OPEN_DD_JS, '请选择')
        print('打开担保方式下拉:', st)
        time.sleep(1)
        options = page1.evaluate(READ_OPTIONS_JS)
        print(f'共 {len(options)} 个担保方式: {options}')
        page1.keyboard.press('Escape')
        time.sleep(0.8)

        result = {}
        for opt in options:
            page1.evaluate(OPEN_DD_JS, '请选择')
            time.sleep(0.8)
            st = page1.evaluate(CLICK_OPTION_JS, opt)
            if st != 'ok':
                print(f'  [{opt}] 选择失败: {st}')
                result[opt] = {'error': st}
                continue
            time.sleep(1.2)
            fields = page1.evaluate(DUMP_JS)
            entry = {'fields': fields}
            # 若有子下拉（如抵押财产类型/质押财产类型），展开枚举其选项
            sub_selects = [f for f in (fields or []) if f['hasSelect'] and f['label'] not in ('担保方式',)]
            sub_opts = {}
            for f in sub_selects:
                ph = next((i['placeholder'] for i in f['inputs'] if i['placeholder']), None)
                if not ph:
                    continue
                page1.evaluate(OPEN_DD_JS, ph)
                time.sleep(0.8)
                sub_opts[f['label']] = page1.evaluate(READ_OPTIONS_JS)
                page1.keyboard.press('Escape')
                time.sleep(0.5)
            if sub_opts:
                entry['sub_options'] = sub_opts
            reqs = [f['label'] for f in (fields or []) if f['required']]
            print(f'  [{opt}] 必填: {reqs}' + (f'  子下拉: {sub_opts}' if sub_opts else ''))
            result[opt] = entry

        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'已保存: {OUT}')
        browser.close()


if __name__ == '__main__':
    main()
