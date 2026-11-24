#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测真实网站法人表单的「证照类型」「类型」下拉真实选项。
复用已保存的登录态，走到完善案件信息页，打开法人表单并转储下拉选项。"""
import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'src'))

from playwright.sync_api import sync_playwright
from test_filing_flow import prepare_login_state, STATE_PATH, build_case_info
from adapters.beijing_court import BeijingCourtAdapter


def dump_options(page, label):
    """打开指定下拉框并返回可见选项文本"""
    click = page.evaluate(r"""(label) => {
        function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }
        const items = Array.from(document.querySelectorAll('uni-forms-item, .uni-forms-item, .fd-com-form-item')).filter(isVisible);
        for (const item of items) {
            const labelEl = item.querySelector('.uni-forms-item__label, .uni-forms-item__title, .fd-form-label, .label, .fd-required-label');
            if (!labelEl) continue;
            const t = (labelEl.innerText || '').replace(/\s+/g, ' ').trim();
            if (t.includes(label)) {
                const triggers = item.querySelectorAll('.uni-data-tree-input, .uni-select, .uni-picker, .uni-input, .input-value, .uni-easyinput, .fd-select-area');
                for (const tr of triggers) {
                    if (isVisible(tr)) { tr.scrollIntoView({behavior: 'instant', block: 'center'}); tr.click(); return {ok: true, label: t}; }
                }
            }
        }
        return {err: 'not found'};
    }""", label)
    page.wait_for_timeout(1500)
    opts = page.evaluate(r"""() => {
        function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }
        const sels = ['.uni-picker-item', '.uni-data-tree-popup-item', '.uni-select-item',
                      '.uni-combox-item', '.uni-data-pickerview-item', '.uni-data-tree-item',
                      '.fd-item', '.item-text', '.uni-list-item', '.uni-popup-item',
                      '.picker-item', '.select-item', '.option-item', '.dropdown-item',
                      'li', '.el-select-dropdown__item', '.el-option'];
        const texts = [];
        for (const o of document.querySelectorAll(sels.join(', '))) {
            if (!isVisible(o)) continue;
            const t = (o.innerText || '').replace(/\s+/g, ' ').trim();
            if (t && !texts.includes(t)) texts.push(t);
        }
        return texts;
    }""")
    page.keyboard.press("Escape")
    page.evaluate("() => { document.body.click(); }")
    page.wait_for_timeout(500)
    return click, opts


def main():
    with open(os.path.join(BASE_DIR, 'test_data', 'test_cases_new.json'), encoding='utf-8') as f:
        raw = [c for c in json.load(f) if c['case_no'] == 'TEST-2026-LEGAL-101'][0]
    case_info = build_case_info(raw)
    case_data = case_info.to_dict()

    prepare_login_state()
    adapter = BeijingCourtAdapter()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=STATE_PATH, viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        page.set_default_timeout(30000)
        page.goto('https://zxfw.court.gov.cn/zxfw/#/pages/index/index', wait_until='domcontentloaded')
        page.wait_for_timeout(2000)
        popup = adapter.navigate_to_filing(page)
        adapter.fill_case_form(popup, case_data)
        adapter.upload_documents(popup, [d.to_dict() for d in case_info.documents])

        # 打开 原告信息 -> 添加法人
        res = adapter._js_click_section_button(popup, '原告信息', '添加法人')
        print('打开法人表单:', res)
        page.wait_for_timeout(3000)

        for label in ('类型', '证照类型', '证件类型'):
            click, opts = dump_options(popup, label)
            print(f'[{label}] click={click}')
            print(f'[{label}] options={opts}')

        browser.close()
    print('PROBE DONE')


if __name__ == '__main__':
    main()
