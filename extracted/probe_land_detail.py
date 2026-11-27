# -*- coding: utf-8 -*-
"""一次性探测：土地使用权弹窗内每个表单项的全部输入控件（placeholder/readonly/type）"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preserve_filing_flow as m
from playwright.sync_api import sync_playwright

DUMP_JS = """() => {
    const items = [...document.querySelectorAll('.el-form-item')];
    const typeItem = items.find(i => (i.querySelector('.el-form-item__label')?.textContent || '').includes('财产类型'));
    if (!typeItem) return null;
    let node = typeItem.parentElement, root = null;
    while (node && node !== document.body) {
        const cls = String(node.className || '');
        const pos = getComputedStyle(node).position;
        if (cls.includes('dialog') || cls.includes('modal') || pos === 'fixed' || pos === 'absolute') { root = node; break; }
        node = node.parentElement;
    }
    if (!root) root = typeItem.parentElement;
    return [...root.querySelectorAll('.el-form-item')].map(item => ({
        label: (item.querySelector('.el-form-item__label')?.textContent || '').replace(/[*\\s]/g, ''),
        required: item.className.includes('is-required'),
        hasSelect: !!item.querySelector('.el-select'),
        hasCascader: !!item.querySelector('.el-cascader'),
        inputs: [...item.querySelectorAll('input, textarea')].map(i => ({
            tag: i.tagName, type: i.type, placeholder: i.placeholder || '',
            readonly: i.readOnly, cls: i.className,
        })),
    })).filter(x => x.label);
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
        adds = []
        for _ in range(6):
            adds = page1.locator('span').filter(has_text=m.re.compile(r'^\+?\s*添加$')).all()
            if adds: break
            time.sleep(2)
        opened = False
        for btn in reversed(adds):
            try:
                btn.click()
                page1.wait_for_selector('input[placeholder="请选择财产类型"]', timeout=4000)
                opened = True; break
            except Exception:
                page1.keyboard.press('Escape')
                page1.evaluate("() => { const d=[...document.querySelectorAll('.el-dialog')].find(d=>d.offsetParent); const x=d?.querySelector('.el-dialog__headerbtn, .el-icon-close'); if(x) x.click(); }")
                time.sleep(1)
        if not opened:
            print('未能打开财产弹窗'); return
        probe_types = os.environ.get('PROBE_TYPES', '土地使用权').split(',')
        all_fields = {}
        for ptype in probe_types:
            page1.get_by_placeholder('请选择财产类型').click()
            time.sleep(1)
            st = page1.evaluate("""(txt) => {
                const dd = [...document.querySelectorAll('.el-select-dropdown')].find(d => (d.getBoundingClientRect().width > 0 && getComputedStyle(d).display !== 'none'));
                if (!dd) return 'no-dropdown';
                const item = [...dd.querySelectorAll('.el-select-dropdown__item')].find(li => li.textContent.trim() === txt);
                if (!item) return 'no-item';
                item.click(); return 'ok';
            }""", ptype)
            print(f'选择{ptype}:', st)
            time.sleep(1.5)
            fields = page1.evaluate(DUMP_JS)
            all_fields[ptype] = fields
            reqs = [f['label'] for f in (fields or []) if f['required']]
            print(f'  [{ptype}] 必填: {reqs}')
        print(json.dumps(all_fields, ensure_ascii=False, indent=1))
        out = m.BASE_DIR / 'results' / 'probe_prop_detail.json'
        out.write_text(json.dumps(all_fields, ensure_ascii=False, indent=1), encoding='utf-8')
        print('已保存:', out)
        browser.close()

if __name__ == '__main__':
    main()
