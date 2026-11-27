# -*- coding: utf-8 -*-
"""生成 4 个保全案件的导入 Excel + 材料 zip 包"""
import io, zipfile, os
from openpyxl import load_workbook
from PIL import Image, ImageDraw

W = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
C = '10X98765432'

def idcard(area, y, m, d, seq):
    base = f'{area}{y:04d}{m:02d}{d:02d}{seq:03d}'
    return base + C[sum(int(x) * w for x, w in zip(base, W)) % 11]

def mini_pdf(title):
    return ('%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n'
            '3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n'
            f'%% {title}\n%%EOF').encode('utf-8')

def mini_png():
    img = Image.new('RGB', (400, 300), (245, 247, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 390, 290], outline=(60, 80, 120), width=3)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()

cases = [
 dict(no='保全TEST-202611-01', name='陈一诉刘二买卖合同纠纷', ptype='诉讼保全', reason='买卖合同纠纷',
      court='广州市天河区人民法院', amount='350000', addr='广州市天河区体育西路100号', contact='陈一', cphone='13811110001',
      atype='自然人', aname='陈一', aid=idcard(440104, 1992, 1, 1, 331), agender='男', aphone='13811110001', aaddr='广州市天河区体育西路100号',
      rtype='自然人', rname='刘二', rid=idcard(440105, 1988, 12, 12, 442), rgender='女', rphone='13922220002', raddr='广州市海珠区新港东路20号',
      props=[dict(property_type='存款', owner='刘二', bank_name='招商银行广州分行', bank_account='6225880212345678',
                  amount='350000', currency='CNY', property_value='350000', property_province='广东', property_city='广州')],
      gtype='交纳保证金', gvalue='350000', gname='', gobject='保证金', gprop='',
      agents=[dict(agent_type='律师', agent_name='周律', agent_cert_no=idcard(440106, 1985, 5, 5, 321), agent_phone='13733330003',
                   agent_license_no='14401202010987654', agent_law_firm='广州国信律师事务所')]),
 dict(no='保全TEST-202611-02', name='孙三诉钱四借款合同纠纷', ptype='诉前保全', reason='借款合同纠纷',
      court='上海市静安区人民法院', amount='1200000', addr='上海市静安区南京西路500号', contact='孙三', cphone='13855550005',
      atype='自然人', aname='孙三', aid=idcard(310106, 1990, 3, 15, 213), agender='男', aphone='13855550005', aaddr='上海市静安区南京西路500号',
      rtype='自然人', rname='钱四', rid=idcard(310110, 1986, 7, 22, 104), rgender='男', rphone='13966660006', raddr='上海市杨浦区控江路800号',
      props=[dict(property_type='房产', owner='钱四', property_value='3000000', property_province='上海', property_city='上海',
                  property_location='上海市杨浦区控江路800弄1号501室', property_cert_no='沪房地杨字(2015)第012345号'),
             dict(property_type='存款', owner='钱四', bank_name='中国建设银行上海分行', bank_account='6217001234567890123',
                  amount='800000', currency='CNY', property_value='800000', property_province='上海', property_city='上海')],
      gtype='设定抵押', gvalue='1500000', gname='', gobject='房产抵押', gprop='房产',
      agents=[]),
 dict(no='保全TEST-202611-03', name='赵七诉孙八股权转让纠纷', ptype='诉讼保全', reason='股权转让纠纷',
      court='南京市鼓楼区人民法院', amount='600000', addr='南京市鼓楼区中山北路200号', contact='赵七', cphone='13877770007',
      atype='自然人', aname='赵七', aid=idcard(320106, 1988, 9, 9, 156), agender='男', aphone='13877770007', aaddr='南京市鼓楼区中山北路200号',
      rtype='自然人', rname='孙八', rid=idcard(320102, 1991, 11, 30, 89), rgender='女', rphone='13988880008', raddr='南京市玄武区珠江路300号',
      props=[dict(property_type='股权', owner='孙八', property_value='600000', property_province='江苏', property_city='南京',
                  stock_company_name='南京云创科技有限公司', stock_ratio='15%')],
      gtype='提供保证人', gvalue='600000', gname='王五', gobject='王五', gprop='',
      agents=[dict(agent_type='律师', agent_name='郑律', agent_cert_no=idcard(320105, 1983, 2, 18, 217), agent_phone='13799990009',
                   agent_license_no='13201201511223344', agent_law_firm='江苏法德律师事务所')]),
 dict(no='保全TEST-202611-04', name='吴九诉郑十机动车交通事故责任纠纷', ptype='诉前保全', reason='机动车交通事故责任纠纷',
      court='成都市武侯区人民法院', amount='180000', addr='成都市武侯区武侯祠大街50号', contact='吴九', cphone='13812120010',
      atype='自然人', aname='吴九', aid=idcard(510107, 1993, 4, 5, 278), agender='女', aphone='13812120010', aaddr='成都市武侯区武侯祠大街50号',
      rtype='自然人', rname='郑十', rid=idcard(510104, 1987, 8, 14, 163), rgender='男', rphone='13934340011', raddr='成都市锦江区春熙路10号',
      props=[dict(property_type='交通运输工具', owner='郑十', property_value='200000', property_province='四川', property_city='成都',
                  vehicle_plate_no='川A88T66', vehicle_location='成都市锦江区春熙路停车场')],
      gtype='设定质押', gvalue='200000', gname='', gobject='存单质押', gprop='存款',
      agents=[]),
]

# ---------- Excel ----------
wb = load_workbook('extracted/test_data/preserve_template_dl.xlsx')
ws = wb.active
headers = [c.value for c in ws[1]]
idx = {h.replace('*', ''): i for i, h in enumerate(headers)}
if ws.max_row > 1:
    ws.delete_rows(2, ws.max_row - 1)  # 清掉模板示例行

def row_for(**kw):
    r = [''] * len(headers)
    for k, v in kw.items():
        if k in idx and v not in (None, ''):
            r[idx[k]] = str(v)
    return r

# 英文字段键 → 中文表头
PROP_MAP = {'property_type': '财产类型', 'owner': '财产所有人', 'bank_name': '开户银行', 'bank_account': '银行账号',
            'amount': '数额', 'currency': '币种', 'property_value': '财产价值', 'property_province': '财产所在省份',
            'property_city': '财产所在城市', 'property_location': '财产详细地址', 'property_cert_no': '产权证号',
            'vehicle_plate_no': '车牌号', 'vehicle_location': '车辆位置', 'stock_company_name': '持股公司名称',
            'stock_ratio': '出资比例', 'stock_name': '股票名称', 'stock_code': '股票代码', 'stock_quantity': '持股数量',
            'stock_reg_location': '发行单位注册地', 'equipment_name': '设备名称'}
AGENT_MAP = {'agent_type': '代理人类型', 'agent_name': '代理人姓名', 'agent_cert_no': '代理人身份证号',
             'agent_phone': '代理人电话', 'agent_license_no': '代理人执业证号', 'agent_law_firm': '代理人律所'}

def cn(d, m):
    return {m.get(k, k): v for k, v in d.items()}

for c in cases:
    main = {
        '案件编号': c['no'], '案件名称': c['name'], '保全类别': c['ptype'], '案由': c['reason'],
        '申请法院': c['court'], '保全金额': c['amount'], '送达地址': c['addr'], '联系人姓名': c['contact'], '联系人电话': c['cphone'],
        '申请人类型': c['atype'], '申请人姓名': c['aname'], '申请人身份证号': c['aid'], '申请人性别': c['agender'],
        '申请人手机号': c['aphone'], '申请人地址': c['aaddr'],
        '被申请人类型': c['rtype'], '被申请人姓名': c['rname'], '被申请人身份证号': c['rid'], '被申请人性别': c['rgender'],
        '被申请人手机号': c['rphone'], '被申请人地址': c['raddr'],
        '担保方式': c['gtype'], '担保价值': c['gvalue'], '担保人姓名': c['gname'],
        '担保物名称': c['gobject'], '担保财产类型': c['gprop'],
    }
    main.update(cn(c['props'][0], PROP_MAP))
    if c['agents']:
        main.update(cn(c['agents'][0], AGENT_MAP))
    ws.append(row_for(**main))
    for p in c['props'][1:]:
        ws.append(row_for(**cn(p, PROP_MAP)))
    for a in c['agents'][1:]:
        ws.append(row_for(**cn(a, AGENT_MAP)))

os.makedirs('保全测试材料包', exist_ok=True)
wb.save('保全测试材料包/保全案件导入-4案.xlsx')

# ---------- 材料 zip ----------
def cat_guarantee(c):
    if c['gtype'] == '提供保证人':
        return f"提供保证人-{c['gobject'] or '保证人'}"
    return c['gtype']

buf = io.BytesIO()
with zipfile.ZipFile(buf, 'w') as z:
    for c in cases:
        z.writestr(f"{c['no']}/保全申请书/保全申请书-{c['no']}.pdf", mini_pdf(c['no'] + ' 保全申请书'))
        z.writestr(f"{c['no']}/起诉状/起诉状-{c['no']}.pdf", mini_pdf(c['no'] + ' 起诉状'))
        z.writestr(f"{c['no']}/证据材料/证据材料-{c['no']}.pdf", mini_pdf(c['no'] + ' 证据'))
        z.writestr(f"{c['no']}/申请人-{c['aname']}-{c['atype']}/{c['aname']}身份证明.png", mini_png())
        z.writestr(f"{c['no']}/被申请人-{c['rname']}-{c['rtype']}/{c['rname']}身份证明.png", mini_png())
        z.writestr(f"{c['no']}/{cat_guarantee(c)}/担保材料-{c['no']}.pdf", mini_pdf(c['no'] + ' 担保材料'))
    z.writestr('使用说明.txt',
               '1. 先在「保全案件」页点「导入 Excel」，选择《保全案件导入-4案.xlsx》\n'
               '2. 再点「批量上传材料」，上传本压缩包（保全材料包-4案.zip）\n'
               '3. 压缩包结构：案件编号/材料类别/文件名\n')
open('保全测试材料包/保全材料包-4案.zip', 'wb').write(buf.getvalue())

for c in cases:
    print(c['no'], c['court'], '| 申请人ID', c['aid'], '| 被申请人ID', c['rid'], '| 担保类别', cat_guarantee(c))
print('OK')
