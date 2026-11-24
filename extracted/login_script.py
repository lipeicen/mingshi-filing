
import sys
sys.path.insert(0, r'C:\Users\Administrator\Desktop\法院自动立案工具方案')
sys.path.insert(0, r'C:\Users\Administrator\Desktop\法院自动立案工具方案\src')

from adapters.beijing_court import BeijingCourtAdapter
from playwright.sync_api import sync_playwright

adapter = BeijingCourtAdapter()
import os
credentials = {
    'username': os.getenv('BEIJING_COURT_USERNAME', ''),
    'password': os.getenv('BEIJING_COURT_PASSWORD', ''),
}
if not credentials['username'] or not credentials['password']:
    raise SystemExit('未配置登录账号：请设置环境变量 BEIJING_COURT_USERNAME / BEIJING_COURT_PASSWORD')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(viewport={'width': 1920, 'height': 1080})
    page = context.new_page()
    if not adapter.login(page, credentials):
        print("LOGIN FAILED")
        sys.exit(1)
    # Save state
    state_path = r'C:\Users\Administrator\Desktop\法院自动立案工具方案\test_data\auth_state.json'
    context.storage_state(path=state_path)
    print(f"Login OK, state saved to {state_path}")
    browser.close()
