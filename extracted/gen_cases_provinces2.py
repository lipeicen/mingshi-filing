#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 6 省(西部/东北方向)测试数据 test_cases_provinces2.json，并做离线校验：
身份证校验位、省份映射、法院名与探测目标一致性。
"""
import json
import os
import random
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'src'))

WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
CODES = '10X98765432'


def make_idcard(area='110101', year=1985, month=6, day=15, seq=101):
    base = f'{area}{year:04d}{month:02d}{day:02d}{seq:03d}'
    return base + CODES[sum(int(d) * w for d, w in zip(base, WEIGHTS)) % 11]


def valid_idcard(no: str) -> bool:
    if len(no) != 18 or not no[:17].isdigit():
        return False
    return CODES[sum(int(d) * w for d, w in zip(no[:17], WEIGHTS)) % 11] == no[17].upper()


DOCS = [
    {"name": "民事起诉状", "type": "起诉状", "path": "documents/complaint.pdf"},
    {"name": "原告身份证明", "type": "身份证明", "path": "documents/plaintiff_id.png"},
    {"name": "被告身份证明", "type": "身份证明", "path": "documents/defendant_id.png"},
    {"name": "证据目录", "type": "证据", "path": "documents/evidence_catalog.pdf"},
    {"name": "授权委托书", "type": "委托书", "path": "documents/authorization.pdf"},
    {"name": "送达地址确认书", "type": "送达地址确认书", "path": "documents/service_address.pdf"},
]

CASES = [
    dict(no='TEST-2026-MP-301', province='云南', court='昆明市五华区人民法院',
         cause='买卖合同纠纷', amount=86000.0,
         claims='判令被告向原告支付茶叶货款人民币86000元及逾期付款利息。',
         facts='2025年3月，被告向原告采购普洱茶一批，货款共计86000元。原告按约发货并经被告验收，被告以市场销售不畅为由拖延付款，至今未付。',
         plaintiff=('杨丽萍', 1990, 3, 8, 12, '云南省昆明市五华区人民中路100号'),
         defendant=('赵国安', 1986, 7, 21, 34, '云南省昆明市盘龙区北京路1200号')),
    dict(no='TEST-2026-MP-302', province='辽宁', court='沈阳市和平区人民法院',
         cause='民间借贷纠纷', amount=150000.0,
         claims='判令被告归还原告借款本金人民币150000元及约定利息。',
         facts='2025年1月，被告因经营周转向原告借款150000元，约定年利率6%，期限一年。借款到期后被告拒不归还，原告多次催要未果。',
         plaintiff=('关晓东', 1982, 11, 5, 56, '辽宁省沈阳市和平区南京北街88号'),
         defendant=('孙立军', 1979, 4, 17, 78, '辽宁省沈阳市铁西区建设大路56号')),
    dict(no='TEST-2026-MP-303', province='重庆', court='重庆市渝中区人民法院',
         cause='机动车交通事故责任纠纷', amount=68000.0,
         claims='判令被告赔偿原告医疗费、误工费、车辆维修费等共计人民币68000元。',
         facts='2025年5月，被告驾驶小型客车在渝中区某路口闯红灯，与原告驾驶的车辆相撞，致原告受伤、车辆受损。交警认定被告负事故全部责任。',
         plaintiff=('陈静怡', 1988, 9, 12, 90, '重庆市渝中区解放碑步行街25号'),
         defendant=('刘长江', 1975, 12, 30, 12, '重庆市江北区观音桥步行街66号')),
    dict(no='TEST-2026-MP-304', province='内蒙古', court='呼和浩特市新城区人民法院',
         cause='房屋租赁合同纠纷', amount=42000.0,
         claims='判令被告向原告支付拖欠租金人民币42000元并返还房屋。',
         facts='2024年10月，原告将位于呼和浩特市新城区的房屋出租给被告，月租金7000元，租期一年。被告自2025年3月起拖欠租金至今。',
         plaintiff=('巴特尔', 1984, 2, 18, 34, '内蒙古呼和浩特市新城区新华东街45号'),
         defendant=('乌云其木格', 1991, 8, 25, 56, '内蒙古呼和浩特市赛罕区大学西路33号')),
    dict(no='TEST-2026-MP-305', province='广西', court='南宁市青秀区人民法院',
         cause='服务合同纠纷', amount=56000.0,
         claims='判令被告向原告支付物业服务费及违约金共计人民币56000元。',
         facts='2024年8月，原告与被告签订设备维保服务合同，服务期一年，费用共计56000元。原告按约完成服务，被告以服务质量异议为由拒付全部费用。',
         plaintiff=('韦国强', 1987, 5, 9, 78, '广西南宁市青秀区民族大道150号'),
         defendant=('蓝秀珍', 1983, 10, 14, 90, '广西南宁市兴宁区朝阳路20号')),
    dict(no='TEST-2026-MP-306', province='新疆', court='乌鲁木齐市天山区人民法院',
         cause='买卖合同纠纷', amount=98000.0,
         claims='判令被告向原告支付棉纱货款人民币98000元及逾期付款利息。',
         facts='2025年4月，被告向原告采购棉纱一批，货款共计98000元。原告按约发货并经被告签收，被告以货物存在色差为由拒付货款，但拒绝退货。',
         plaintiff=('艾合买提·玉山', 1980, 6, 22, 12, '新疆乌鲁木齐市天山区解放南路77号'),
         defendant=('古丽米娜·阿布都', 1989, 1, 16, 34, '新疆乌鲁木齐市沙依巴克区友好北路15号')),
]


def build():
    cases = []
    for i, c in enumerate(CASES):
        pname, py, pm, pd_, pseq, paddr = c['plaintiff']
        dname, dy, dm, dd, dseq, daddr = c['defendant']
        cases.append({
            'case_no': c['no'],
            'case_type': '民事案件',
            'court_code': 'beijing',
            'court_name': c['court'],
            'court_province': c['province'],
            'case_cause': c['cause'],
            'amount': c['amount'],
            'claims': c['claims'],
            'facts': c['facts'],
            'plaintiff': {'name': pname, 'idcard': make_idcard(year=py, month=pm, day=pd_, seq=pseq),
                          'phone': f'1390000{3000 + i * 2:04d}'[-11:], 'address': paddr},
            'defendant': {'name': dname, 'idcard': make_idcard(year=dy, month=dm, day=dd, seq=dseq),
                          'phone': f'1380000{3001 + i * 2:04d}'[-11:], 'address': daddr},
            'documents': list(DOCS),
            'agents': [{
                'name': f'测试代理人{i + 1}号',
                'idcard': make_idcard(year=1985, month=5, day=20, seq=601 + i),
                'phone': f'1370000{3100 + i:04d}'[-11:],
                'type': '执业律师',
                'license_no': f'11101202110567{i:02d}'[:17],
                'work_unit': '北京大成律师事务所',
                'principals': [pname],
            }],
        })
    return cases


def phone_ok(p):
    return len(p) == 11 and p.isdigit() and p.startswith('1')


def main():
    random.seed(2026)
    from adapters.beijing_court import BeijingCourtAdapter
    adapter = BeijingCourtAdapter.__new__(BeijingCourtAdapter)  # 仅需省份映射方法

    cases = build()
    errors = []
    for c in cases:
        for role in ('plaintiff', 'defendant'):
            p = c[role]
            if not valid_idcard(p['idcard']):
                errors.append(f"{c['case_no']} {role} 身份证校验位不合法: {p['idcard']}")
            if not phone_ok(p['phone']):
                errors.append(f"{c['case_no']} {role} 手机号不合法: {p['phone']}")
        for a in c['agents']:
            if not valid_idcard(a['idcard']):
                errors.append(f"{c['case_no']} 代理人身份证校验位不合法: {a['idcard']}")
            if not phone_ok(a['phone']):
                errors.append(f"{c['case_no']} 代理人手机号不合法: {a['phone']}")
            if a['principals'] != [c['plaintiff']['name']]:
                errors.append(f"{c['case_no']} 被代理人与原告不一致")
        pid = adapter.province_id_from_name(c['court_province'])
        if not pid:
            errors.append(f"{c['case_no']} 省份映射失败: {c['court_province']}")
        if not c['court_name'] or not c['court_province']:
            errors.append(f"{c['case_no']} 法院或省份为空")
        for doc in c['documents']:
            if not os.path.exists(os.path.join(BASE_DIR, doc['path'])):
                errors.append(f"{c['case_no']} 材料缺失: {doc['path']}")

    out = os.path.join(BASE_DIR, 'test_data', 'test_cases_provinces2.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

    print(f'已生成 {len(cases)} 条案件 -> {out}')
    for c in cases:
        pid = adapter.province_id_from_name(c['court_province'])
        print(f"  {c['case_no']} | {c['court_province']}({pid}) | {c['court_name']} | {c['case_cause']}")
    if errors:
        print('\n校验失败:')
        for e in errors:
            print('  -', e)
        sys.exit(1)
    print('离线校验全部通过')


if __name__ == '__main__':
    main()
