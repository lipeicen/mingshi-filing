#!/usr/bin/env python3
import os
# -*- coding: utf-8 -*-
"""端到端流程测试：阅读须知 -> 选择立案案由 -> 下一步 -> 上传诉讼材料
验证修复后的 _select_case_cause 完整流程（含案由未选时下一步被拦截的场景）"""
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from playwright.sync_api import sync_playwright
from adapters.beijing_court import BeijingCourtAdapter


def active_step(page):
    return page.evaluate("""() => {
        const on = document.querySelector('.uni-steps__row-title.on');
        return on ? on.innerText.trim() : '';
    }""")


def main():
    adapter = BeijingCourtAdapter()
    case_data = {
        'court_name': '北京市海淀区人民法院',
        'case_reason': '买卖合同纠纷',
        'applicant_type': '为他人或公司等组织申请',
        'metadata': {},
    }
    passed = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on('dialog', lambda d: d.dismiss())
        page.goto('file://' + os.path.join(os.path.dirname(__file__), 'mock_flow.html'))
        page.wait_for_timeout(500)

        assert active_step(page) == '阅读须知', f"初始步骤错误: {active_step(page)}"
        passed.append('初始在阅读须知页')

        # 场景1：案由未选时直接点下一步，应被拦截（模拟真实校验）
        page.evaluate("""() => {
            document.getElementById('page-notice').classList.remove('active');
            document.getElementById('page-cause').classList.add('active');
            document.querySelectorAll('.uni-steps__row-title').forEach(t => t.classList.remove('on'));
            document.querySelector('.uni-steps__row-title[data-step="3"]').classList.add('on');
        }""")
        r = adapter._click_page_bottom_next(page)
        page.wait_for_timeout(500)
        assert active_step(page) == '选择立案案由', '未选案由不应进入下一步'
        passed.append(f'未选案由时下一步被正确拦截 (click={r})')

        # 场景2：与真实环境一致——调用 _select_case_cause 时已处于案由步骤页
        #（须知页的前置推进由 navigate_to_filing / fill_case_form 完成）
        page.evaluate("""() => {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.getElementById('page-cause').classList.add('active');
            document.querySelectorAll('.uni-steps__row-title').forEach(t => t.classList.remove('on'));
            document.querySelector('.uni-steps__row-title[data-step="3"]').classList.add('on');
        }""")

        adapter._select_case_cause(page, case_data)
        page.wait_for_timeout(1000)

        state = page.evaluate("""() => {
            const area = document.querySelector('.uni-data-tree .selected-area');
            return {
                text: (area.innerText || '').trim(),
                isPlaceholder: area.classList.contains('placeholder'),
                dialogOpen: !!document.querySelector('.uni-data-tree-dialog')
            };
        }""")
        print('案由选择后状态:', state)
        assert state['text'] == '买卖合同纠纷' and not state['isPlaceholder'], f"案由未选中: {state}"
        assert not state['dialogOpen'], '弹层未关闭'
        passed.append('案由已通过下拉框选中: 买卖合同纠纷')

        step = active_step(page)
        print('当前步骤:', step)
        assert step == '上传诉讼材料', f'应进入上传诉讼材料，实际: {step}'
        passed.append('成功进入「上传诉讼材料」步骤')

        browser.close()

    print()
    for i, item in enumerate(passed, 1):
        print(f'  PASS {i}: {item}')
    print('\nALL FLOW TESTS PASSED')


if __name__ == '__main__':
    main()
