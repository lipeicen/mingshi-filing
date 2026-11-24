#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上传页 Excel 流程浏览器验证。"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent
errors, failed = [], []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    page.on('response', lambda r: failed.append(f'{r.status} {r.url}') if r.status >= 400 else None)

    page.goto('http://localhost:7100/upload', wait_until='networkidle')
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / 'verify_upload2.png'))

    # 选择 Excel 文件 → 服务端解析预览
    page.set_input_files('input[accept*="json"]', str(OUT.parent / 'test_import.xlsx'))
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT / 'verify_xlsx_preview.png'))
    print('preview rows:', page.locator('tbody tr').count())

    # 模板下载按钮存在且链接正确
    tpl = page.locator('a[href="/api/cases/template"]')
    print('template link:', tpl.count())
    browser.close()

print('CONSOLE ERRORS:', json.dumps(errors, ensure_ascii=False)[:1000] if errors else 'none')
print('FAILED REQUESTS:', json.dumps(failed, ensure_ascii=False)[:1000] if failed else 'none')
sys.exit(1 if errors or failed else 0)
