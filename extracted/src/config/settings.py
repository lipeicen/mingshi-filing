import os
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False
from .db_config import get_db_config, get_court_credentials

load_dotenv()

class Settings:
    # 浏览器配置
    BROWSER_HEADLESS = os.getenv('BROWSER_HEADLESS', 'true').lower() == 'true'
    BROWSER_POOL_SIZE = int(os.getenv('BROWSER_POOL_SIZE', '5'))
    BROWSER_TIMEOUT = int(os.getenv('BROWSER_TIMEOUT', '30000'))

    # 验证码配置
    CAPTCHA_API_KEY = os.getenv('CAPTCHA_API_KEY', '')
    CAPTCHA_API_URL = os.getenv('CAPTCHA_API_URL', 'https://api.captcha-service.com/solve')

    # 数据库连接配置：环境变量 > court_filing_civil.system_config > 默认值
    DB_CONFIG = get_db_config()

    # 法院账号配置：环境变量 > system_users 第一个活跃用户
    COURT_CREDENTIALS = {
        'beijing': get_court_credentials('beijing'),
        'shanghai': get_court_credentials('shanghai'),
    }

    # 日志配置
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'logs/filing.log')

    # 截图配置
    SCREENSHOT_DIR = os.getenv('SCREENSHOT_DIR', 'screenshots')

    # 文档配置
    DOCUMENT_DIR = os.getenv('DOCUMENT_DIR', 'documents')

settings = Settings()
