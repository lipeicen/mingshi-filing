# -*- coding: utf-8 -*-
"""基于后端模板生成 3 个新财产类型的保全测试案 Excel（基金/债权/土地使用权）"""
import io
import json
import urllib.request

import openpyxl

BASE = 'http://localhost:8100'

def req(path, method='GET', body=None, token=None, raw=False):
    r = urllib.request.Request(BASE + path, method=method)
    if token:
        r.add_header('Authorization', 'Bearer ' + token)
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        r.add_header('Content-Type', 'application/json; charset=utf-8')
    with urllib.request.urlopen(r, data=data) as resp:
        return resp.read() if raw else json.loads(resp.read().decode('utf-8'))

# 1. 登录
login = req('/api/auth/login', 'POST', {'username': 'admin', 'password': 'admin123'})
token = login.get('token') or login.get('data', {}).get('token')
assert token, login
print('登录成功')

# 2. 下载模板
tpl = req('/api/preserve/template', token=token, raw=True)
wb = openpyxl.load_workbook(io.BytesIO(tpl))
ws = wb.active
headers = [c.value for c in ws[1]]
print('模板列数:', len(headers))

# 3. 基础数据（复用已验证的当事人结构）
def base(case_no, name, court, amount, ptype, prop_value):
    return {
        '案件编号*': case_no, '案件名称*': name, '保全类别': '诉讼保全',
        '案由': '买卖合同纠纷', '申请法院*': court, '保全金额*': str(amount),
        '送达地址': '广州市天河区体育西路100号', '联系人姓名': '陈一', '联系人电话': '13811110001',
        '申请人类型': '自然人', '申请人姓名*': '陈一', '申请人身份证号*': '440104199201013312',
        '申请人性别': '男', '申请人手机号*': '13811110001', '申请人地址': '广州市天河区体育西路100号',
        '被申请人类型': '自然人', '被申请人姓名*': '刘二', '被申请人身份证号*': '440105198812124427',
        '被申请人性别': '女', '被申请人手机号': '13922220002', '被申请人地址': '广州市海珠区新港东路20号',
        '财产类型*': ptype, '财产所有人': '刘二', '财产价值': str(prop_value),
        '担保方式': '交纳保证金', '担保价值': str(amount), '担保物名称': '保证金',
        '代理人类型': '律师', '代理人姓名': '周律', '代理人身份证号': '440106198505053215',
        '代理人电话': '13733330003', '代理人执业证号': '14401202010987654', '代理人律所': '广州国信律师事务所',
    }

cases = [
    # 基金：必填 发行单位注册地 + 基金名称
    {**base('保全TEST-202611-05', '陈一诉刘二买卖合同纠纷（基金保全）', '南京市鼓楼区人民法院', 240000, '基金', 240000),
     '发行单位注册地': '江苏省', '基金名称': '华夏稳健增长混合型证券投资基金', '基金数量': '200000'},
    # 债权：描述类，必填 财产描述
    {**base('保全TEST-202611-06', '陈一诉刘二买卖合同纠纷（债权保全）', '杭州市西湖区人民法院', 300000, '债权', 300000),
     '财产描述': '被申请人刘二对第三人张三享有的到期借款债权，借款本金30万元及约定利息，借款到期日2026年6月30日'},
    # 土地使用权：必填 财产详细地址 + 土地面积（+面积单位）
    {**base('保全TEST-202611-07', '陈一诉刘二买卖合同纠纷（土地保全）', '成都市武侯区人民法院', 500000, '土地使用权', 500000),
     '财产所在省份': '四川', '财产所在城市': '成都', '财产详细地址': '四川省成都市武侯区武科东三路9号地块',
     '土地面积': '800', '面积单位': '平方米'},
]

# 模板可能自带示例行，清掉数据行
if ws.max_row > 1:
    ws.delete_rows(2, ws.max_row - 1)
idx = {h: i + 1 for i, h in enumerate(headers)}
missing_cols = [k for c in cases for k in c if k not in idx]
assert not missing_cols, f'模板缺少列: {missing_cols}'
for c in cases:
    row = ws.max_row + 1
    for k, v in c.items():
        ws.cell(row=row, column=idx[k], value=v)

out = '保全测试材料包/保全案件导入-新增3案.xlsx'
wb.save(out)
print('已生成:', out)

# 4. dry=1 预览校验
boundary = '----pytestboundary1234567890'
file_bytes = open(out, 'rb').read()
parts = []
parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="new3.xlsx"\r\nContent-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n'.encode('utf-8'))
parts.append(file_bytes)
parts.append(f'\r\n--{boundary}--\r\n'.encode('utf-8'))
body = b''.join(parts)
r = urllib.request.Request(BASE + '/api/preserve/import?dry=1', data=body, method='POST')
r.add_header('Authorization', 'Bearer ' + token)
r.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
with urllib.request.urlopen(r) as resp:
    result = json.loads(resp.read().decode('utf-8'))
print('DRY 预览:', json.dumps(result, ensure_ascii=False, indent=1)[:2000])
