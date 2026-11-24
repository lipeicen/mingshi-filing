
import sys, os, json, time
sys.path.insert(0, r"C:\Users\Administrator\Desktop\法院自动立案工具方案\src")

from playwright.sync_api import sync_playwright
from adapters.beijing_court import BeijingCourtAdapter

log_file = r"C:\Users\Administrator\Desktop\法院自动立案工具方案\test_visual_verify12.log"

import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(name)s:%(funcName)s:%(lineno)d - %(message)s',
    handlers=[
        logging.FileHandler(log_file, mode='w', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

SS_DIR = r"C:\Users\Administrator\Desktop\法院自动立案工具方案\screenshots\visual"
STATE_PATH = r"C:\Users\Administrator\Desktop\法院自动立案工具方案\test_data\auth_state.json"
os.makedirs(SS_DIR, exist_ok=True)

def take_screenshot(page, name):
    path = os.path.join(SS_DIR, f"VERIFY12_{name}.png")
    page.screenshot(path=path, full_page=False)
    logger.info(f"截图: {path}")

# Step 1: Re-login with headless=False
logger.info("Step 1: Re-login")
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
        logger.error("Login failed")
        sys.exit(1)
    context.storage_state(path=STATE_PATH)
    browser.close()
    logger.info("Login OK, state saved")

# Step 2: Run test with headless=True
logger.info("Step 2: Run visual test")
with open(r"C:\Users\Administrator\Desktop\法院自动立案工具方案\test_data\test_cases.json", 'r', encoding='utf-8') as f:
    cases = json.load(f)
case = cases[0]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={'width': 1280, 'height': 900},
        storage_state=STATE_PATH
    )
    page = context.new_page()
    
    adapter = BeijingCourtAdapter()
    
    page = adapter.navigate_to_filing(page)
    logger.info("Navigation done")
    take_screenshot(page, "01_navigated")
    
    form = adapter.fill_case_form(page, case)
    logger.info(f"Form fill: {form}")
    take_screenshot(page, "02_form_filled")
    
    upload = adapter.upload_documents(page, case)
    logger.info(f"Upload: {upload}")
    take_screenshot(page, "03_uploaded")
    
    parties = adapter.fill_party_form(page, case)
    logger.info(f"Parties: {parties}")
    take_screenshot(page, "04_party_filled")
    
    preview = adapter.complete_case_info_and_preview(page, case)
    logger.info(f"Preview: {preview}")
    take_screenshot(page, "05_preview")
    
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1000)
    take_screenshot(page, "06_preview_scrolled")
    
    browser.close()

logger.info("Test 12 complete")
