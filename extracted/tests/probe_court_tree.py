#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法院树完整性探测：对目标省份逐一走真实 _set_xzfy_province + _click_court_card 路径，
验证目标法院是否存在于法院树且能被选中。"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'src'))

from playwright.sync_api import sync_playwright
from test_filing_flow import prepare_login_state, STATE_PATH
from adapters.beijing_court import BeijingCourtAdapter

TARGETS = [
    ('云南', '昆明市五华区人民法院'),
    ('辽宁', '沈阳市和平区人民法院'),
    ('重庆', '重庆市渝中区人民法院'),
    ('内蒙古', '呼和浩特市新城区人民法院'),
    ('广西', '南宁市青秀区人民法院'),
    ('新疆', '乌鲁木齐市天山区人民法院'),
]


def main():
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
        popup.wait_for_selector("text=选择受理法院", timeout=30000)
        popup.wait_for_timeout(2000)

        results = []
        for province, court in TARGETS:
            adapter._set_xzfy_province(popup, province, court)
            ok = adapter._click_court_card(popup, court)
            state = popup.evaluate("""() => {
                function find(v, t) { if (!v) return null;
                    const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);
                    if (tag === t) return v;
                    for (const c of v.$children || []) { const r = find(c, t); if (r) return r; }
                    return null; }
                const x = find(document.querySelector('uni-app').__vue__, 'xzfy');
                return x ? {n: (x.fyList || []).length, fymc: x.fymc, fyId: x.fyId} : {err: 'no xzfy'};
            }""")
            results.append((province, court, ok, state))
            print(f"[{'PASS' if ok else 'FAIL'}] {province} | {court} | fyList={state.get('n')} fymc={state.get('fymc')}")
            popup.wait_for_timeout(1000)

        browser.close()
    passed = sum(1 for r in results if r[2])
    print(f'PROBE DONE: {passed}/{len(results)} 通过')


if __name__ == '__main__':
    main()
