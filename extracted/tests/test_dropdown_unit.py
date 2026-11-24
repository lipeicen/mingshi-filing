#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用模拟 wsla 页面验证 _select_cause_from_tree 修复"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))  # 包结构: adapters/, utils/, config/

# captcha_solver 可能依赖第三方库，提前打桩
import types
for mod in ('utils.captcha_solver',):
    pass

from playwright.sync_api import sync_playwright
from adapters.beijing_court import BeijingCourtAdapter

def main():
    adapter = BeijingCourtAdapter()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto('file://' + os.path.join(os.path.dirname(__file__), 'mock_wsla.html'))
        page.wait_for_timeout(500)

        ok = adapter._select_cause_from_tree(page, '买卖合同纠纷')
        print('RESULT ok =', ok)

        state = page.evaluate("""() => {
            const area = document.querySelector('.uni-data-tree .selected-area');
            return {
                text: (area.innerText || '').trim(),
                isPlaceholder: area.classList.contains('placeholder'),
                dialogOpen: !!document.querySelector('.uni-data-tree-dialog')
            };
        }""")
        print('FINAL STATE =', state)

        # 也验证 _click_page_bottom_next 能点中 uni-button
        page.evaluate("""() => {
            window.__nextClicked = false;
            document.querySelector('uni-button').addEventListener('click', () => { window.__nextClicked = true; });
        }""")
        r = adapter._click_page_bottom_next(page)
        print('NEXT CLICK =', r, 'fired =', page.evaluate("() => window.__nextClicked"))

        browser.close()
        assert ok, '案由选择失败'
        assert state['text'] == '买卖合同纠纷' and not state['isPlaceholder'] and not state['dialogOpen']
        print('ALL ASSERTIONS PASSED')

if __name__ == '__main__':
    main()
