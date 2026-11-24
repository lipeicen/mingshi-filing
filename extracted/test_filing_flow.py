#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端测试：登录一次保存 storage_state，每个案件独立 context，避免页面状态污染。
"""
import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime
from loguru import logger

# Visual test screenshot helper
_SCREENSHOT_DIR = None
def set_screenshot_dir(d):
    global _SCREENSHOT_DIR
    _SCREENSHOT_DIR = d

def take_screenshot(page, name, full_page=False):
    """Take screenshot if in visual mode"""
    if _SCREENSHOT_DIR:
        try:
            path = os.path.join(_SCREENSHOT_DIR, f"{name}.png")
            page.screenshot(path=path, timeout=5000, full_page=full_page)
            logger.info(f"截图: {path}")
        except Exception as e:
            logger.debug(f"截图失败 {name}: {e}")


try:
    import pymysql
except ImportError:
    pymysql = None

base_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(base_dir, 'src')
sys.path.insert(0, src_dir)

from config import settings
DB_CONFIG = settings.DB_CONFIG


def load_config():
    """从 system_config 和 system_users 表加载配置，环境变量优先。"""
    defaults = {
        'BEIJING_COURT_USERNAME': '',
        'BEIJING_COURT_PASSWORD': '',
        'DEFAULT_COURT_NAME': '北京市海淀区人民法院',
        'DEFAULT_COURT_CODE': 'beijing',
        'DEFAULT_CASE_REASON': '买卖合同纠纷',
        'DEFAULT_CASE_TYPE': '民事案件',
        'COURT_BASE_URL': 'https://zxfw.court.gov.cn',
        'DRY_RUN_DEFAULT': 'false',
        'STATE_MAX_AGE_MINUTES': '10080',
    }
    cfg = defaults.copy()
    if not pymysql:
        return cfg
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT config_key, config_value FROM system_config")
        db_cfg = {row[0]: row[1] or '' for row in cursor.fetchall()}
        cfg.update({k: v for k, v in db_cfg.items() if k in defaults})
        # 账号密码从 system_users 读取（取第一个 is_active=1 的用户）
        cursor.execute("SELECT username, password FROM system_users WHERE is_active=1 ORDER BY id LIMIT 1")
        user_row = cursor.fetchone()
        if user_row:
            cfg['BEIJING_COURT_USERNAME'] = user_row[0] or cfg['BEIJING_COURT_USERNAME']
            cfg['BEIJING_COURT_PASSWORD'] = user_row[1] or cfg['BEIJING_COURT_PASSWORD']
        conn.close()
    except Exception as e:
        logger.warning(f"读取配置失败，使用默认值: {e}")
    # 环境变量覆盖
    for k in defaults:
        env_val = os.getenv(k)
        if env_val is not None:
            cfg[k] = env_val
    return cfg


SYS_CONFIG = load_config()


# DB field mapping: internal key -> actual DB column name
DB_FIELD_MAP = {
    'case_no': 'case_no',
    'case_name': 'case_name',
    'case_type': 'case_type',
    'court_code': 'court_code',
    'court_name': 'court_name',
    'case_cause': 'case_reason',
    'claims': 'claim',
    'facts': 'facts',
    'amount': 'claim_amount',
    'applicant_type': 'applicant_type',
    'plaintiff_name': 'applicant_name',
    'plaintiff_id': 'applicant_id',
    'plaintiff_phone': 'applicant_phone',
    'plaintiff_address': 'applicant_address',
    'defendant_name': 'respondent_name',
    'defendant_id': 'respondent_id',
    'defendant_phone': 'respondent_phone',
    'defendant_address': 'respondent_address',
    'court_province': 'court_province',
    # 当事人扩展字段（列名与既有库结构一致：nature=当事人类型、uscc=统一社会信用代码、
    # cert_no=法定代表人证件号码、reg_address=注册地、tel=固定电话）
    'plaintiff_uscc': 'applicant_uscc',
    'plaintiff_litigant_type': 'applicant_nature',
    'plaintiff_legal_person': 'applicant_legal_person',
    'plaintiff_legal_person_id': 'applicant_cert_no',
    'plaintiff_legal_person_phone': 'applicant_tel',
    'plaintiff_registered_address': 'applicant_reg_address',
    'defendant_uscc': 'respondent_uscc',
    'defendant_litigant_type': 'respondent_nature',
    'defendant_legal_person': 'respondent_legal_person',
    'defendant_legal_person_id': 'respondent_cert_no',
    'defendant_legal_person_phone': 'respondent_tel',
    'defendant_registered_address': 'respondent_reg_address',
}

def get_db_value(row, key, default=''):
    keys = [DB_FIELD_MAP.get(key, key), key]
    seen = set()
    for k in keys:
        if not k or k in seen:
            continue
        seen.add(k)
        if k in row and row[k] is not None:
            return row[k]
        lk = k.lower()
        if lk in row and row[lk] is not None:
            return row[lk]
    return default


from playwright.sync_api import sync_playwright
from adapters import BeijingCourtAdapter
from models import CaseInfo, Party, CaseDocument

DATA_PATH = os.path.join(base_dir, 'test_data', 'test_cases.json')
RESULT_DIR = os.path.join(base_dir, 'results')
LOG_DIR = os.path.join(base_dir, 'logs')
STATE_PATH = os.path.join(base_dir, 'test_data', 'auth_state.json')
for d in (RESULT_DIR, LOG_DIR, os.path.dirname(STATE_PATH)):
    os.makedirs(d, exist_ok=True)

logger.add(
    os.path.join(LOG_DIR, 'test_filing_flow.log'),
    rotation="10 MB",
    retention="7 days",
    level="INFO",
    encoding="utf-8"
)


def load_cases(path=None):
    with open(path or DATA_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_cases_from_db(limit=10, case_nos=None):
    """Load pending cases from DB + case_files. Uses DB_FIELD_MAP soft mapping.

    case_nos: 可选，只加载指定案件编号（仍要求 status=0）。"""
    if not pymysql:
        raise ImportError('请安装 pymysql: pip install pymysql')

    case_fields = list(set(v for v in DB_FIELD_MAP.values() if v))
    if 'id' not in case_fields:
        case_fields.insert(0, 'id')
    case_fields_sql = ', '.join(case_fields)

    where, params = 'status = 0', []
    if case_nos:
        where += f" AND case_no IN ({', '.join(['%s'] * len(case_nos))})"
        params.extend(case_nos)
    params.append(limit)

    conn = pymysql.connect(**DB_CONFIG)
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(f"""
            SELECT {case_fields_sql} FROM cases
            WHERE {where}
            ORDER BY id DESC
            LIMIT %s
        """, tuple(params))
        case_rows = cursor.fetchall()
        case_ids = [r['id'] for r in case_rows]
        file_rows = []
        agent_rows = []
        if case_ids:
            placeholders = ','.join(['%s'] * len(case_ids))
            cursor.execute(f"""
                SELECT case_id, file_category, file_name, file_path
                FROM case_files
                WHERE case_id IN ({placeholders})
            """, tuple(case_ids))
            file_rows = cursor.fetchall()
            cursor.execute(f"""
                SELECT case_id, agent_type, agent_name, agent_cert_type, agent_cert_no,
                       agent_phone, agent_license_no, agent_law_firm
                FROM agents
                WHERE case_id IN ({placeholders})
                ORDER BY id
            """, tuple(case_ids))
            agent_rows = cursor.fetchall()
    finally:
        conn.close()

    files_map = {}
    for fr in file_rows:
        files_map.setdefault(fr['case_id'], []).append(fr)
    agents_map = {}
    for ar in agent_rows:
        agents_map.setdefault(ar['case_id'], []).append(ar)

    cases_map = {}
    for row in case_rows:
        case_id = row['id']
        amount_raw = get_db_value(row, 'amount')
        try:
            amount = float(amount_raw) if amount_raw not in (None, '') else 0.0
        except Exception:
            amount = 0.0

        cases_map[case_id] = {
            'case_no': get_db_value(row, 'case_no'),
            'case_name': get_db_value(row, 'case_name'),
            'case_type': get_db_value(row, 'case_type') or SYS_CONFIG.get('DEFAULT_CASE_TYPE', '民事案件'),
            'court_code': get_db_value(row, 'court_code') or SYS_CONFIG.get('DEFAULT_COURT_CODE', 'beijing'),
            'court_name': get_db_value(row, 'court_name') or SYS_CONFIG.get('DEFAULT_COURT_NAME', '北京市海淀区人民法院'),
            'court_province': get_db_value(row, 'court_province'),
            'case_cause': get_db_value(row, 'case_cause') or SYS_CONFIG.get('DEFAULT_CASE_REASON', '买卖合同纠纷'),
            'applicant_type': (get_db_value(row, 'applicant_type') or '').replace('自然人', '') or '为他人或公司等组织申请',
            'amount': amount,
            'claims': get_db_value(row, 'claims'),
            'facts': get_db_value(row, 'facts'),
            'plaintiff': {
                'name': get_db_value(row, 'plaintiff_name'),
                'idcard': get_db_value(row, 'plaintiff_id') or get_db_value(row, 'plaintiff_uscc'),
                'phone': get_db_value(row, 'plaintiff_phone'),
                'address': get_db_value(row, 'plaintiff_address'),
                'litigant_type': get_db_value(row, 'plaintiff_litigant_type') or '自然人',
                'legal_person': get_db_value(row, 'plaintiff_legal_person'),
                'legal_person_id': get_db_value(row, 'plaintiff_legal_person_id'),
                'legal_person_phone': get_db_value(row, 'plaintiff_legal_person_phone'),
                'registered_address': get_db_value(row, 'plaintiff_registered_address'),
            },
            'defendant': {
                'name': get_db_value(row, 'defendant_name'),
                'idcard': get_db_value(row, 'defendant_id') or get_db_value(row, 'defendant_uscc'),
                'phone': get_db_value(row, 'defendant_phone'),
                'address': get_db_value(row, 'defendant_address'),
                'litigant_type': get_db_value(row, 'defendant_litigant_type') or '自然人',
                'legal_person': get_db_value(row, 'defendant_legal_person'),
                'legal_person_id': get_db_value(row, 'defendant_legal_person_id'),
                'legal_person_phone': get_db_value(row, 'defendant_legal_person_phone'),
                'registered_address': get_db_value(row, 'defendant_registered_address'),
            },
            'agents': [
                {
                    'name': ar.get('agent_name') or '',
                    'idcard': ar.get('agent_cert_no') or '',
                    'phone': ar.get('agent_phone') or '',
                    'type': ar.get('agent_type') or '执业律师',
                    'license_no': ar.get('agent_license_no') or '',
                    'work_unit': ar.get('agent_law_firm') or '',
                    # 库中无被代理人字段，默认代理原告（测试数据全部为此情形）
                    'principals': [get_db_value(row, 'plaintiff_name')],
                }
                for ar in agents_map.get(case_id, [])
            ],
            'documents': [],
        }
        for fr in files_map.get(case_id, []):
            fp = fr.get('file_path', '')
            if fp and os.path.exists(fp):
                cases_map[case_id]['documents'].append({
                    'name': fr.get('file_name') or fr.get('file_category') or '材料',
                    'type': fr.get('file_category') or '其他材料',
                    'path': fp,
                })
    return list(cases_map.values())


def build_case_info(raw):

    def build_party(data, party_type):
        return Party(
            name=data['name'],
            idcard=data['idcard'],
            phone=data['phone'],
            address=data.get('address', ''),
            party_type=party_type,
            party_category=data.get('litigant_type', data.get('party_category', '自然人')),
            legal_person=data.get('legal_person', ''),
            legal_person_id=data.get('legal_person_id', ''),
            legal_person_phone=data.get('legal_person_phone', ''),
            registered_address=data.get('registered_address', ''),
            org_type=data.get('org_type', '有限责任公司')
        )

    parties = [
        build_party(raw['plaintiff'], '原告'),
        build_party(raw['defendant'], '被告')
    ]
    
    # 添加代理人
    for agent_data in raw.get('agents', []):
        parties.append(Party(
            name=agent_data['name'],
            idcard=agent_data['idcard'],
            phone=agent_data['phone'],
            address=agent_data.get('address', ''),
            party_type='代理人',
            agent_type=agent_data.get('type', '执业律师'),
            license_no=agent_data.get('license_no', ''),
            work_unit=agent_data.get('work_unit', ''),
            represented_party=agent_data.get('principals', [''])[0] if agent_data.get('principals') else ''
        ))
    
    docs = []
    docs = [
        CaseDocument(
            name=d['name'],
            path=d['path'] if os.path.isabs(d['path']) else os.path.join(base_dir, d['path']),
            doc_type=d['type'],
            description=d['name']
        )
        for d in raw['documents']
    ]
    return CaseInfo(

        case_type=raw['case_type'],
        court_code=raw['court_code'],
        parties=parties,
        court_name=raw['court_name'],
        claims=raw['claims'],
        facts=raw['facts'],
        amount=raw['amount'],
        documents=docs,
        case_cause=raw.get('case_cause', ''),
        metadata={
            'case_no': raw['case_no'],
            'case_cause': raw.get('case_cause', ''),
        },
        applicant_type=raw.get('applicant_type', '')
    )


def save_report(report, suffix=''):
    report_path = os.path.join(RESULT_DIR, f'test_filing_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}{suffix}.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"测试报告: {report_path}")
    return report_path


def _validate_state() -> bool:
    """验证 storage_state：文件在有效期内且包含 zxfwtoken"""
    if not Path(STATE_PATH).exists():
        return False
    # 先检查本地是否有 token
    try:
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            state = json.load(f)
        has_token = any(
            item.get('name') == 'zxfwtoken' and item.get('value')
            for origin in state.get('origins', [])
            for item in origin.get('localStorage', [])
        )
        if not has_token:
            logger.warning("storage_state 缺少 zxfwtoken，需重新登录")
            return False
    except Exception as e:
        logger.warning(f"读取 storage_state 失败: {e}")
        return False
    max_age = int(SYS_CONFIG.get('STATE_MAX_AGE_MINUTES', '10080')) * 60  # 7 days
    if time.time() - Path(STATE_PATH).stat().st_mtime > max_age:
        logger.warning(f"storage_state 超过 {SYS_CONFIG.get('STATE_MAX_AGE_MINUTES', '60')} 分钟，强制重新登录")
        return False
    adapter = BeijingCourtAdapter()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=STATE_PATH, viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        # Listen to console
        page.on('console', lambda msg: logger.info(f'[BROWSER] {msg.text[:500]}'))
        try:
            page.goto(f"{adapter.base_url}/zxfw/#/pages/pc/home/index", wait_until="domcontentloaded", timeout=10000)
            adapter._wait(2)
            content = page.content()
            valid = "在线立案" in content and "密码登录" not in content
            if not valid:
                logger.warning(f"storage_state 已失效，需要重新登录")
            return valid
        except Exception as e:
            logger.warning(f"验证登录态失败: {e}")
            return False
        finally:
            context.close()
            browser.close()


def prepare_login_state():
    """登录态有效则复用，否则重新登录（headless=False 提高验证码成功率）"""
    if _validate_state():
        logger.info(f"登录态有效，跳过重新登录: {STATE_PATH}")
        return
    adapter = BeijingCourtAdapter()
    credentials = {
        'username': os.getenv('BEIJING_COURT_USERNAME', ''),
        'password': os.getenv('BEIJING_COURT_PASSWORD', ''),
    }
    if not credentials['username'] or not credentials['password']:
        raise Exception('未配置登录账号：请在 .env 或环境变量中设置 BEIJING_COURT_USERNAME / BEIJING_COURT_PASSWORD')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        if not adapter.login(page, credentials):
            raise Exception('登录失败')
        context.storage_state(path=STATE_PATH)
        browser.close()
    logger.info(f"登录态已保存: {STATE_PATH}")


def run_case(browser, raw, index):
    case_info = build_case_info(raw)
    case_no = case_info.metadata['case_no']
    logger.info(f"--- [{index}] 测试案件 {case_no} ---")

    case_data = case_info.to_dict()
    case_data['court_province'] = raw.get('court_province', '') or case_data.get('metadata', {}).get('court_province', '')
    
    res = {
        'case_no': case_no,
        'status': '未知',
        'message': '',
        'case_id': None,
        'steps': [],
        'court_name': case_data.get('court_name', ''),
        'case_type': case_data.get('case_type', ''),
        'case_cause': case_data.get('case_reason', ''),
        'parties_count': len(case_data.get('parties', [])),
        'documents_count': len(case_data.get('documents', [])),
        'amount': case_data.get('amount', case_data.get('claim_amount', 0)),
        'submitted_at': None,
        'duration_seconds': 0
    }

    adapter = BeijingCourtAdapter()
    context = browser.new_context(storage_state=STATE_PATH, viewport={'width': 1920, 'height': 1080})
    page = context.new_page()
    page.set_default_timeout(30000)  # 30s default timeout for all operations
    start_time = datetime.now()
    try:
        # 先回到首页，再导航立案
        page.goto('https://zxfw.court.gov.cn/zxfw/#/pages/index/index', wait_until='domcontentloaded')
        time.sleep(2)
        popup = adapter.navigate_to_filing(page, province=case_data.get('court_province', '') or '北京')
        if not popup:
            raise Exception('未能进入立案表单页面')
        take_screenshot(popup, f"{case_no}_01_navigated")
        adapter.fill_case_form(popup, case_data)
        take_screenshot(popup, f"{case_no}_02_case_form_filled")
        if case_info.documents:
            adapter.upload_documents(popup, [d.to_dict() for d in case_info.documents])
            take_screenshot(popup, f"{case_no}_03_documents_uploaded")
        # 填写当事人信息并提交
        adapter.fill_party_form(popup, case_data)
        take_screenshot(popup, f"{case_no}_04_party_filled")
        adapter.complete_case_info_and_preview(popup, case_data)
        take_screenshot(popup, f"{case_no}_05_preview")
        # Scroll down to capture agent/third-party info
        try:
            popup.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            popup.wait_for_timeout(1000)
            take_screenshot(popup, f"{case_no}_05_preview_scrolled", full_page=True)
        except Exception:
            pass


        # ===== 预览值与传输值一致性验证 =====
        try:
            preview_data = popup.evaluate("""() => {
                const result = {};
                result.yg_text = [];
                result.bg_text = [];
                result.dlr_text = [];
                document.querySelectorAll('.uni-card, .card, [class*="party"], [class*="litigant"]').forEach(card => {
                    const t = card.innerText || '';
                    if (t.includes('原告') || t.includes('申请人')) result.yg_text.push(t);
                    if (t.includes('被告') || t.includes('被申请人')) result.bg_text.push(t);
                    if (t.includes('代理人') || t.includes('委托诉讼代理人')) result.dlr_text.push(t);
                });
                result.full_text = document.body.innerText.substring(0, 5000);
                return result;
            }""")
            import json as _json
            logger.info(f"预览页面数据: {_json.dumps(preview_data, ensure_ascii=False)[:3000]}")
        except Exception as e:
            logger.warning(f"抓取预览数据失败: {e}")

        dry_run = os.getenv('COURT_FILING_DRY_RUN', SYS_CONFIG.get('DRY_RUN_DEFAULT', 'false')).lower() in ('true', '1', 'yes')
        submit = adapter.submit_case(popup, case_data, dry_run=dry_run)
        take_screenshot(popup, f"{case_no}_06_submitted")
        success = bool(submit.get('success'))
        res['status'] = ('待提交' if dry_run else '已提交') if success else '已驳回'
        res['message'] = submit.get('message', '')
        res['case_id'] = submit.get('case_id')
        res['submitted_at'] = datetime.now().isoformat()
        res['duration_seconds'] = int((datetime.now() - start_time).total_seconds())
        logger.info(f"结果: {res['status']} | {res['message']}")
    except Exception as e:
        logger.exception(f"案件 {case_no} 异常")
        res['status'] = '异常'
        res['message'] = str(e)
    finally:
        try:
            context.storage_state(path=STATE_PATH)
            logger.info(f"已保存当前会话状态: {STATE_PATH}")
        except Exception as e:
            logger.warning(f"保存会话状态失败: {e}")
        context.close()
    return res


def run_all_cases():
    raw_cases = load_cases()
    logger.info(f"加载 {len(raw_cases)} 个测试案件")

    report = {
        'time': datetime.now().isoformat(),
        'total': len(raw_cases),
        'results': []
    }

    prepare_login_state()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for i, raw in enumerate(raw_cases, 1):
            res = run_case(browser, raw, i)
            report['results'].append(res)
            save_report(report, suffix=f'_progress_{i}of{len(raw_cases)}')
            time.sleep(2)
        browser.close()

    save_report(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--case-idx', type=int, default=-1, help='只跑指定索引的案件（0-based），-1 跑全部')
    parser.add_argument('--headless', type=lambda x: x.lower() in ('true', '1', 'yes'), default=True)
    parser.add_argument('--visual', action='store_true', help='可视化测试模式：headless=False 并在关键步骤截图')
    parser.add_argument('--screenshot-dir', default='screenshots/visual', help='可视化测试截图保存目录')
    parser.add_argument('--from-db', action='store_true', help='从数据库 cases/case_files 加载案件和材料')
    parser.add_argument('--db-limit', type=int, default=10, help='从数据库加载的案件数量上限')
    parser.add_argument('--db-case-nos', default=None, help='只跑指定的数据库案件编号（逗号分隔，仍要求 status=0）')
    parser.add_argument('--data-file', default=None, help='测试案件 JSON 路径（默认 test_data/test_cases.json）')
    args = parser.parse_args()

    raw_cases = load_cases_from_db(args.db_limit, case_nos=args.db_case_nos.split(',') if args.db_case_nos else None) if args.from_db else load_cases(args.data_file)
    if args.case_idx >= 0:
        raw_cases = [raw_cases[args.case_idx]]

    report = {
        'time': __import__('datetime').datetime.now().isoformat(),
        'total': len(raw_cases),
        'results': []
    }
    prepare_login_state()

    # Visual mode forces headless=False
    headless_mode = False if args.visual else args.headless
    screenshot_dir = os.path.join(base_dir, args.screenshot_dir) if args.visual else None
    if screenshot_dir:
        os.makedirs(screenshot_dir, exist_ok=True)
        set_screenshot_dir(screenshot_dir)
        logger.info(f"可视化测试模式，截图保存到: {screenshot_dir}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless_mode)
        for i, raw in enumerate(raw_cases, 1):
            res = run_case(browser, raw, i)
            report['results'].append(res)
            save_report(report, suffix=f'_progress_{i}of{len(raw_cases)}')
            time.sleep(2)
        browser.close()

    save_report(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))

