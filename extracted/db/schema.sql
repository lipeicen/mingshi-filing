-- =============================================================
-- 法院自动立案工具 数据库结构（MySQL 8.0+，utf8mb4）
-- 库名：court_filing_civil
-- 表：system_config / system_users / cases / agents / case_files
-- 说明：列命名与既有部署保持一致；import_cases_to_db.py --init-schema
--       会在已有库上自动补齐缺失列，不会破坏已有数据。
-- =============================================================

CREATE DATABASE IF NOT EXISTS court_filing_civil
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;

USE court_filing_civil;

-- ---------- 系统配置（键值对，环境变量优先于本表） ----------
CREATE TABLE IF NOT EXISTS system_config (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  config_key    VARCHAR(128) NOT NULL UNIQUE COMMENT '配置键，如 DEFAULT_COURT_NAME',
  config_value  TEXT         NULL COMMENT '配置值',
  updated_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- 法院登录账号（取第一个 is_active=1 的用户） ----------
CREATE TABLE IF NOT EXISTS system_users (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  username    VARCHAR(64)  NOT NULL COMMENT '人民法院在线服务账号（手机号）',
  password    VARCHAR(128) NOT NULL COMMENT '登录密码',
  court_code  VARCHAR(32)  NOT NULL DEFAULT 'beijing',
  is_active   TINYINT      NOT NULL DEFAULT 1,
  created_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- 案件主表（status=0 表示待立案，会被工具读取） ----------
CREATE TABLE IF NOT EXISTS cases (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  case_no          VARCHAR(64)  NOT NULL UNIQUE COMMENT '案件编号（业务唯一键）',
  case_name        VARCHAR(255) NULL,
  case_type        VARCHAR(50)  NOT NULL DEFAULT '民事案件',
  court_code       VARCHAR(20)  NOT NULL DEFAULT 'beijing',
  court_name       VARCHAR(100) NOT NULL,
  court_province   VARCHAR(50)  NOT NULL DEFAULT '北京',
  case_reason      VARCHAR(200) NOT NULL COMMENT '立案案由，如 民间借贷纠纷',
  claim            TEXT         NULL COMMENT '诉讼请求',
  facts            TEXT         NULL COMMENT '事实与理由',
  claim_amount     DECIMAL(15,2) NOT NULL DEFAULT 0 COMMENT '标的金额(元)',
  applicant_type   VARCHAR(64)  NULL COMMENT '申请人类型（页面选项文本）',

  -- 原告（自然人或法人/非法人组织）
  applicant_name          VARCHAR(128) NOT NULL,
  applicant_id            VARCHAR(64)  NULL COMMENT '原告身份证号（自然人）',
  applicant_uscc          VARCHAR(50)  NULL COMMENT '统一社会信用代码（法人）',
  applicant_phone         VARCHAR(32)  NULL,
  applicant_address       TEXT         NULL,
  applicant_nature        VARCHAR(50)  NOT NULL DEFAULT '自然人' COMMENT '当事人类型：自然人/法人/非法人组织',
  applicant_gender        VARCHAR(10)  NULL COMMENT '性别（由身份证号推导）',
  applicant_birth         DATE         NULL COMMENT '出生日期（由身份证号推导）',
  applicant_age           INT          NULL COMMENT '年龄（由身份证号推导）',
  applicant_legal_person  VARCHAR(64)  NULL COMMENT '法定代表人/负责人（法人时必填）',
  applicant_cert_type     VARCHAR(20)  NULL COMMENT '法定代表人证件类型',
  applicant_cert_no       VARCHAR(64)  NULL COMMENT '法定代表人证件号码',
  applicant_tel           VARCHAR(32)  NULL COMMENT '固定电话',
  applicant_reg_address   TEXT         NULL COMMENT '注册地/登记地（法人）',

  -- 被告
  respondent_name          VARCHAR(128) NOT NULL,
  respondent_id            VARCHAR(64)  NULL,
  respondent_uscc          VARCHAR(50)  NULL,
  respondent_phone         VARCHAR(32)  NULL,
  respondent_address       TEXT         NULL,
  respondent_nature        VARCHAR(50)  NOT NULL DEFAULT '自然人',
  respondent_gender        VARCHAR(10)  NULL,
  respondent_birth         DATE         NULL,
  respondent_age           INT          NULL,
  respondent_legal_person  VARCHAR(64)  NULL,
  respondent_cert_type     VARCHAR(20)  NULL,
  respondent_cert_no       VARCHAR(64)  NULL,
  respondent_tel           VARCHAR(32)  NULL,
  respondent_reg_address   TEXT         NULL,

  status           INT          NOT NULL DEFAULT 0 COMMENT '0=待立案 1=已提交 2=已驳回 9=无需处理',
  remark           TEXT         NULL,
  created_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
                   ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- 代理人表（一个案件可有多个代理人） ----------
CREATE TABLE IF NOT EXISTS agents (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  case_id          INT          NOT NULL COMMENT 'cases.id',
  agent_type       VARCHAR(20)  NOT NULL DEFAULT '执业律师' COMMENT '代理人类型（页面选项）',
  agent_name       VARCHAR(50)  NOT NULL,
  agent_gender     VARCHAR(10)  NULL,
  agent_cert_type  VARCHAR(20)  NULL DEFAULT '居民身份证',
  agent_cert_no    VARCHAR(64)  NOT NULL COMMENT '代理人证件号码',
  agent_phone      VARCHAR(20)  NULL,
  agent_license_no VARCHAR(50)  NULL COMMENT '律师执业证号',
  agent_law_firm   VARCHAR(100) NULL COMMENT '律师事务所/工作单位',
  created_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_case_id (case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- 案件材料表 ----------
CREATE TABLE IF NOT EXISTS case_files (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  case_id       INT          NOT NULL COMMENT 'cases.id',
  file_category VARCHAR(64)  NOT NULL COMMENT '材料类别（页面选项，如 起诉状）',
  file_name     VARCHAR(255) NOT NULL,
  file_path     VARCHAR(512) NOT NULL COMMENT '服务器本地绝对路径',
  upload_status INT          NOT NULL DEFAULT 0,
  created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_case_id (case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
