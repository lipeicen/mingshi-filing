#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""管理后台浏览器验证：逐页打开、收集控制台错误、截图。"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = 'http://localhost:7100'
OUT = Path(__file__).parent
errors = []
failed_reqs = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    page.on('requestfailed', lambda r: failed_reqs.append(r.url))
    page.on('response', lambda r: failed_reqs.append(f'{r.status} {r.url}') if r.status >= 400 else None)

    for name, path in [('dashboard', '/'), ('cases', '/cases'), ('upload', '/upload'), ('runs', '/runs')]:
        page.goto(f'{BASE}{path}', wait_until='networkidle')
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / f'verify_{name}.png'))
        print(f'[{name}] title={page.title()!r} h1={page.locator("h1").first.inner_text() if page.locator("h1").count() else "?"}')

    # 交互检查：案件页打开详情弹窗
    page.goto(f'{BASE}/cases', wait_until='networkidle')
    page.wait_for_timeout(800)
    page.locator('tbody tr').first.click()
    page.wait_for_timeout(800)
    dlg = page.locator('[role="dialog"]')
    print('[cases] detail dialog visible:', dlg.is_visible())
    if dlg.is_visible():
        page.screenshot(path=str(OUT / 'verify_case_detail.png'))
        page.keyboard.press('Escape')

    # 交互检查：勾选前 2 个待立案案件，确认立案弹窗出现
    page.wait_for_timeout(400)
    boxes = page.locator('tbody [role="checkbox"]')
    if boxes.count() >= 2:
        boxes.nth(0).click()
        boxes.nth(1).click()
        page.wait_for_timeout(300)
        btn = page.locator('button', has_text='立案').first
        print('[cases] run button enabled:', btn.first.is_enabled())
        btn.first.click()
        page.wait_for_timeout(600)
        alert = page.locator('[role="alertdialog"]')
        print('[cases] confirm dialog visible:', alert.is_visible())
        if alert.is_visible():
            page.screenshot(path=str(OUT / 'verify_confirm.png'))
            page.get_by_role('button', name='取消').click()

    # 交互检查：上传页选择文件（用真实数据文件）
    page.goto(f'{BASE}/upload', wait_until='networkidle')
    page.set_input_files('input[type=file]', str(OUT.parent / 'extracted' / 'test_data' / 'test_cases_provinces2.json'))
    page.wait_for_timeout(1000)
    page.screenshot(path=str(OUT / 'verify_upload_preview.png'))
    rows = page.locator('tbody tr').count()
    print(f'[upload] preview rows: {rows}')

    browser.close()

print('CONSOLE ERRORS:', json.dumps(errors, ensure_ascii=False)[:2000] if errors else 'none')
print('FAILED REQUESTS:', json.dumps(failed_reqs, ensure_ascii=False)[:2000] if failed_reqs else 'none')
sys.exit(1 if errors or failed_reqs else 0)
