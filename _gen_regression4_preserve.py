# -*- coding: utf-8 -*-
"""全量回归测试包：货币现金/股票/债券/机器设备 4 案（Excel + 材料 zip）"""
import io
import json
import urllib.request
import zipfile
from pathlib import Path

import openpyxl

BASE = 'http://localhost:8100'

def api(path, method='GET', body=None, token=None, raw=False):
    r = urllib.request.Request(BASE + path, method=method)
    if token:
        r.add_header('Authorization', 'Bearer ' + token)
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        r.add_header('Content-Type', 'application/json; charset=utf-8')
    with urllib.request.urlopen(r, data=data) as resp:
        return resp.read() if raw else json.loads(resp.read().decode('utf-8'))

def upload(path, file_bytes, filename, token, field='file'):
    boundary = '----pytestboundary1234567890'
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n').encode() + file_bytes + f'\r\n--{boundary}--\r\n'.encode()
    r = urllib.request.Request(BASE + path, data=body, method='POST')
    r.add_header('Authorization', 'Bearer ' + token)
    r.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
    return json.loads(urllib.request.urlopen(r).read().decode())

login = api('/api/auth/login', 'POST', {'username': 'admin', 'password': 'admin123'})
token = login['token']
print('登录成功')

tpl = api('/api/preserve/template', token=token, raw=True)
wb = openpyxl.load_workbook(io.BytesIO(tpl))
ws = wb.active
headers = [c.value for c in ws[1]]
if ws.max_row > 1:
    ws.delete_rows(2, ws.max_row - 1)
idx = {h: i + 1 for i, h in enumerate(headers)}

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
        '数额': str(prop_value), '币种': 'CNY',
        '担保方式': '交纳保证金', '担保价值': str(amount), '担保物名称': '保证金',
        '代理人类型': '律师', '代理人姓名': '周律', '代理人身份证号': '440106198505053215',
        '代理人电话': '13733330003', '代理人执业证号': '14401202010987654', '代理人律所': '广州国信律师事务所',
    }

cases = [
    # 货币现金：仅 数额+币种+财产价值
    base('保全TEST-202611-08', '陈一诉刘二买卖合同纠纷（现金保全）', '广州市越秀区人民法院', 180000, '货币现金', 180000),
    # 股票：发行单位注册地+股票名称(+股票代码/持股数量)
    {**base('保全TEST-202611-09', '陈一诉刘二买卖合同纠纷（股票保全）', '深圳市福田区人民法院', 420000, '股票', 420000),
     '发行单位注册地': '广东省', '股票名称': '中国平安', '股票代码': '601318', '持股数量': '10000'},
    # 债券：发行单位注册地+债券名称+债券面值
    {**base('保全TEST-202611-10', '陈一诉刘二买卖合同纠纷（债券保全）', '武汉市江汉区人民法院', 360000, '债券', 360000),
     '发行单位注册地': '湖北省', '债券名称': '2021年湖北省政府一般债券(五期)', '债券面值': '360000'},
    # 机器设备：设备名称
    {**base('保全TEST-202611-11', '陈一诉刘二买卖合同纠纷（设备保全）', '西安市雁塔区人民法院', 260000, '机器设备', 260000),
     '财产所在省份': '陕西', '财产所在城市': '西安', '设备名称': '数控加工中心CNC-850两台'},
]

for c in cases:
    row = ws.max_row + 1
    for k, v in c.items():
        if k in idx:
            ws.cell(row=row, column=idx[k], value=v)

xlsx_path = Path('保全测试材料包/保全案件导入-回归4案.xlsx')
wb.save(xlsx_path)
print('已生成:', xlsx_path)

# dry 预览
res = upload('/api/preserve/import?dry=1', xlsx_path.read_bytes(), 'reg4.xlsx', token)
print('DRY 预览:', json.dumps(res, ensure_ascii=False)[:1500])

# 正式导入
res = upload('/api/preserve/import', xlsx_path.read_bytes(), 'reg4.xlsx', token)
print('导入:', json.dumps(res, ensure_ascii=False)[:500])

# 材料 zip（复用 01 案材料文件）
src = Path('extracted/documents/uploads/preserve/保全TEST-202611-01')
zip_path = Path('保全测试材料包/保全材料包-回归4案.zip')
new_cases = [c['案件编号*'] for c in cases]
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
    for nc in new_cases:
        for cat_dir in sorted(src.iterdir()):
            if not cat_dir.is_dir():
                continue
            for f in cat_dir.iterdir():
                z.write(f, f'{nc}/{cat_dir.name}/{f.name.replace("保全TEST-202611-01", nc)}')
res = upload('/api/preserve/files/batch', zip_path.read_bytes(), 'pack.zip', token)
print('材料上传:', json.dumps(res, ensure_ascii=False)[:400])
