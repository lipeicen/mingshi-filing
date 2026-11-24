#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库配置和法院账号的集中加载器。

优先级：环境变量 > court_filing_civil.system_config / system_users > 默认值
"""
import os
import logging

try:
    import pymysql
except ImportError:
    pymysql = None

logger = logging.getLogger(__name__)


def _default_db_config():
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": os.getenv("DB_NAME", "court_filing_civil"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "charset": os.getenv("DB_CHARSET", "utf8mb4"),
    }


def _load_system_config(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT config_key, config_value FROM system_config")
    return {row[0]: row[1] or "" for row in cursor.fetchall()}


def _load_first_active_user(conn):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, password FROM system_users WHERE is_active=1 ORDER BY id LIMIT 1"
    )
    return cursor.fetchone()


def get_db_config():
    """读取数据库连接配置。环境变量优先，否则读取 system_config。"""
    cfg = _default_db_config()
    if not pymysql:
        return cfg

    try:
        conn = pymysql.connect(**cfg)
        try:
            db_cfg = _load_system_config(conn)
            key_map = {
                "DB_HOST": "host",
                "DB_USER": "user",
                "DB_PASSWORD": "password",
                "DB_NAME": "database",
                "DB_PORT": "port",
                "DB_CHARSET": "charset",
            }
            for cfg_key, db_key in key_map.items():
                if cfg_key in db_cfg and db_cfg[cfg_key]:
                    cfg[db_key] = (
                        int(db_cfg[cfg_key]) if db_key == "port" else db_cfg[cfg_key]
                    )
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"从 system_config 读取数据库配置失败，使用默认值: {e}")
    return cfg


def get_court_credentials(court_code="beijing"):
    """读取法院登录账号。system_users 第一个活跃用户优先，环境变量兜底。"""
    prefix = court_code.upper()
    username = os.getenv(f"{prefix}_COURT_USERNAME", "")
    password = os.getenv(f"{prefix}_COURT_PASSWORD", "")

    if not pymysql:
        return {"username": username, "password": password}

    try:
        conn = pymysql.connect(**get_db_config())
        try:
            row = _load_first_active_user(conn)
            if row:
                username = row[0] or username
                password = row[1] or password
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"从 system_users 读取账号失败，使用环境变量: {e}")

    return {"username": username, "password": password}
