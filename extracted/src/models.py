from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum
from datetime import datetime

class FilingStatus(Enum):
    # 立案状态
    PENDING = "待提交"
    SUBMITTING = "提交中"
    SUBMITTED = "已提交"
    REVIEWING = "审核中"
    APPROVED = "已通过"
    REJECTED = "已驳回"
    COMPLETED = "已完成"

class CaseType(Enum):
    # 案件类型
    CIVIL = "民事案件"
    CRIMINAL = "刑事案件"
    ADMINISTRATIVE = "行政案件"
    EXECUTION = "执行案件"

@dataclass
class Party:
    # 当事人信息
    name: str
    idcard: str
    phone: str
    address: str = ""
    party_type: str = "原告"  # 原告/被告/第三人/代理人
    cert_no: str = ""  # 证件号码（与 idcard 一致，兼容法院页面）
    cert_type: str = ""  # 证件类型（自然人默认居民身份证，法人默认营业执照）
    
    def __post_init__(self):
        """根据当事人类型设置默认证件类型"""
        if not self.cert_type:
            if self.party_category == "法人":
                self.cert_type = "营业执照"
            else:
                self.cert_type = "居民身份证"
    party_category: str = "自然人"  # 自然人/法人/其他组织
    gender: str = ""  # 性别
    nation: str = "汉族"  # 民族
    # 法人专属字段
    legal_person: str = ""  # 法定代表人/负责人姓名
    legal_person_id: str = ""  # 法定代表人证件号码
    legal_person_phone: str = ""  # 法定代表人手机号码（默认使用 phone）
    registered_address: str = ""  # 注册地/登记地
    org_type: str = "有限责任公司"  # 类型（有限责任公司/股份有限公司等）
    
    # 代理人专属字段
    agent_type: str = ""  # 代理人类型（执业律师/基层法律服务工作者/近亲属/工作人员/公民代理等）
    license_no: str = ""  # 执业证号/工作证号
    work_unit: str = ""  # 单位/工作单位
    represented_party: str = ""  # 被代理人姓名（关联原告/被告）
    position: str = ""  # 职务/职位（自然人用，如：其他、经理、员工等）

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "idcard": self.idcard,
            "cert_no": self.cert_no or self.idcard,
            "cert_type": self.cert_type,
            "phone": self.phone,
            "address": self.address,
            "party_type": self.party_type,
            "party_category": self.party_category,
            "litigant_type": self.party_category,  # 兼容字段：自然人/法人/其他组织
            "gender": self.gender,
            "nation": self.nation,
            "agent_type": self.agent_type,
            "license_no": self.license_no,
            "work_unit": self.work_unit,
            "represented_party": self.represented_party,
            "position": self.position,
            # 法人字段
            "legal_person": self.legal_person,
            "legal_person_id": self.legal_person_id,
            "legal_person_phone": self.legal_person_phone or self.phone,
            "registered_address": self.registered_address or self.address,
            "org_type": self.org_type,
        }

@dataclass
class CaseDocument:
    # 案件材料
    name: str
    path: str
    doc_type: str  # 起诉状/身份证明/证据/委托书等
    description: str = ""
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "type": self.doc_type,
            "description": self.description
        }

@dataclass
class CaseInfo:
    # 案件信息
    case_type: str
    court_code: str
    parties: List[Party]
    claims: str
    facts: str
    amount: float
    documents: List[CaseDocument]
    metadata: dict = field(default_factory=dict)
    court_name: str = ""
    applicant_type: str = ""  # 本人申请 / 为他人或公司等组织申请
    case_cause: str = ""  # 案由（如：买卖合同纠纷），立案时必填

    def to_dict(self) -> dict:
        d = {
            "case_type": self.case_type,
            "court_code": self.court_code,
            "court_name": self.court_name,
            "parties": [p.to_dict() for p in self.parties],
            "claims": self.claims,
            "facts": self.facts,
            "amount": self.amount,
            "documents": [d.to_dict() for d in self.documents],
            "metadata": self.metadata,
            "applicant_type": self.applicant_type,
            "case_cause": self.case_cause,
            "case_reason": self.case_cause,  # 兼容适配器 _select_case_cause 读取的键
        }
        return d

@dataclass
class FilingResult:
    # 立案结果
    case_id: Optional[str] = None
    status: FilingStatus = FilingStatus.PENDING
    message: str = ""
    court_code: str = ""
    court_name: str = ""
    steps: List[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "status": self.status.value,
            "message": self.message,
            "court_code": self.court_code,
            "court_name": self.court_name,
            "steps": self.steps,
            "created_at": self.created_at
        }
