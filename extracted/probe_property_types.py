# -*- coding: utf-8 -*-
"""探测法院网站保全财产线索弹窗：枚举全部财产类型 + 每种类型的表单项（必填/选填）
复用 preserve_filing_flow 的登录与建案流程，只探测不提交。
输出 extracted/results/probe_property_types.json
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preserve_filing_flow as m
from playwright.sync_api import sync_playwright

OUT = m.BASE_DIR / 'results' / 'probe_property_types.json'

READ_FIELDS_JS = """() => {
    const items = [...document.querySelectorAll('.el-form-item')];
    const typeItem = items.find(i => (i.querySelector('.el-form-item__label')?.textContent || '').includes('财产类型'));
    if (!typeItem) return null;
    // 从「财产类型」向上找模态容器（fixed/absolute 或类名含 dialog/modal 的祖先）
    let node = typeItem.parentElement;
    let root = null;
    while (node && node !== document.body) {
        const cls = String(node.className || '');
        const pos = getComputedStyle(node).position;
        if (cls.includes('dialog') || cls.includes('modal') || pos === 'fixed' || pos === 'absolute') { root = node; break; }
        node = node.parentElement;
    }
    if (!root) root = typeItem.parentElement;
    return [...root.querySelectorAll('.el-form-item')].map(item => {
        const rawLabel = item.querySelector('.el-form-item__label')?.textContent || '';
        const input = item.querySelector('input, textarea');
        return {
            label: rawLabel.replace(/[*\\s]/g, ''),
            required: item.className.includes('is-required') || rawLabel.trim().startsWith('*'),
            placeholder: input ? (input.placeholder || '') : '',
            kind: item.querySelector('.el-select') ? 'select' : 'input',
        };
    }).filter(x => x.label);
}"""


def click_type_option(page1, opt_text):
    """打开财产类型下拉并精确点击选项"""
    page1.get_by_placeholder('请选择财产类型').click()
    time.sleep(0.8)
    clicked = page1.evaluate("""(txt) => {
        const dd = [...document.querySelectorAll('.el-select-dropdown')].find(d => (d.getBoundingClientRect().width > 0 && getComputedStyle(d).display !== 'none'));
        if (!dd) return 'no-dropdown';
        const item = [...dd.querySelectorAll('.el-select-dropdown__item')].find(li => li.textContent.trim() === txt);
        if (!item) return 'no-item';
        item.click();
        return 'ok';
    }""", opt_text)
    time.sleep(1.2)
    return clicked


def main():
    m.load_case_data('保全TEST-202611-01')  # 仅为进入向导提供基本数据
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=m.HEADLESS)
        ctx = browser.new_context(viewport={'width': 1400, 'height': 900})
        page = ctx.new_page()
        if not m.auto_login(page):
            print('登录失败')
            return
        page1 = m.create_preservation(page)
        time.sleep(2)

        # 打开财产线索的添加弹窗：从最后一个「添加」往前试，直到财产类型下拉出现
        adds = []
        for _ in range(6):
            adds = page1.locator('span').filter(has_text=m.re.compile(r'^\+?\s*添加$')).all()
            if adds:
                break
            time.sleep(2)
        print(f'页面添加按钮数: {len(adds)}')
        opened = False
        for btn in reversed(adds):
            try:
                btn.click()
                page1.wait_for_selector('input[placeholder="请选择财产类型"]', timeout=4000)
                opened = True
                break
            except Exception:
                # 点错弹窗则关掉再试
                page1.keyboard.press('Escape')
                page1.evaluate("() => { const d=[...document.querySelectorAll('.el-dialog')].find(d=>d.offsetParent); const x=d?.querySelector('.el-dialog__headerbtn, .el-icon-close'); if(x) x.click(); }")
                time.sleep(1)
        if not opened:
            print('未能打开财产弹窗')
            return
        print('财产弹窗已打开')

        # 枚举财产类型选项
        page1.get_by_placeholder('请选择财产类型').click()
        time.sleep(1)
        options = page1.evaluate("""() => {
            const dd = [...document.querySelectorAll('.el-select-dropdown')].find(d => (d.getBoundingClientRect().width > 0 && getComputedStyle(d).display !== 'none'));
            if (!dd) return [];
            return [...dd.querySelectorAll('.el-select-dropdown__item')].map(li => li.textContent.trim()).filter(t => t);
        }""")
        print(f'共 {len(options)} 个财产类型: {options}')
        page1.keyboard.press('Escape')   # 枚举后关闭下拉，避免下一轮点击变成收起
        time.sleep(0.8)

        import os
        only = os.environ.get('PROBE_ONLY', '')
        if only:
            options = [o for o in options if o in only.split(',')]
        result = {}
        for opt in options:
            st = click_type_option(page1, opt)
            if st != 'ok':
                print(f'  [{opt}] 选择失败: {st}')
                result[opt] = {'error': st}
                continue
            fields = page1.evaluate(READ_FIELDS_JS)
            result[opt] = {'fields': fields}
            reqs = [f['label'] for f in (fields or []) if f['required']]
            print(f'  [{opt}] 必填: {reqs}')

        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'已保存: {OUT}')
        browser.close()


if __name__ == '__main__':
    main()
