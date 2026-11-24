#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测广东省城市对象结构与 getFyList 调用方式。

结论（抓包确认）：getFyList 的 city 参数必须是城市名字符串（citymc），
传对象会被序列化成 JSON 串导致返回空列表。生产代码已按此修复，
本脚本保留多签名试探仅作历史诊断记录。"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'src'))

from playwright.sync_api import sync_playwright
from test_filing_flow import prepare_login_state, STATE_PATH
from adapters.beijing_court import BeijingCourtAdapter

SWITCH_JS = r"""(provinceId) => {
    function find(v, tagName) {
        if (!v) return null;
        const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);
        if (tag === tagName) return v;
        for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }
        return null;
    }
    const app = document.querySelector('uni-app').__vue__;
    const header = find(app, 'commonHeader');
    const x = find(app, 'xzfy');
    if (!x) return {err: 'no xzfy'};
    uni.setStorageSync('provinceId', provinceId);
    if (header) {
        const idx = (header.provinces || []).indexOf(provinceId);
        header.currentAreaIndex = idx > 0 ? idx : 1;
    }
    x.value = provinceId;
    x.citymc = ''; x.fyId = ''; x.fymc = ''; x.currentIndex = 0; x.chooseValue = 0;
    x.cityList = []; x.fyList = [];
    if (typeof x.getCityList === 'function') x.getCityList();
    x.$forceUpdate();
    return {switched: provinceId};
}"""

DUMP_CITY_JS = r"""() => {
    function find(v, tagName) {
        if (!v) return null;
        const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);
        if (tag === tagName) return v;
        for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }
        return null;
    }
    const x = find(document.querySelector('uni-app').__vue__, 'xzfy');
    return {
        cityList_full: JSON.parse(JSON.stringify(x.cityList || [])),
        fyList: (x.fyList || []).map(f => ({text: f.text, value: f.value})),
        citymc: x.citymc, fymc: x.fymc,
    };
}"""

CITY_JS = r"""(cityKw) => {
    function find(v, tagName) {
        if (!v) return null;
        const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);
        if (tag === tagName) return v;
        for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }
        return null;
    }
    const x = find(document.querySelector('uni-app').__vue__, 'xzfy');
    const cities = x.cityList || [];
    const city = cities.find(c => JSON.stringify(c).includes(cityKw));
    if (!city) return {err: 'city not found'};
    x.citymc = city.text || city.name || city.label || city.citymc || '';
    // 依次尝试 getFyList 的不同签名
    const tries = [
        () => x.getFyList(city),
        () => x.getFyList(city.value || city.id || city.dm),
        () => x.getFyList(),
    ];
    const called = [];
    for (const t of tries) {
        try { const r = t(); called.push('ok'); } catch (e) { called.push('err:' + String(e).slice(0, 80)); }
    }
    x.$forceUpdate();
    return {city: JSON.parse(JSON.stringify(city)), called};
}"""


def main():
    prepare_login_state()
    adapter = BeijingCourtAdapter()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=STATE_PATH, viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        page.set_default_timeout(30000)
        page.goto('https://zxfw.court.gov.cn/zxfw/#/pages/index/index', wait_until='domcontentloaded')
        page.wait_for_timeout(2000)
        popup = adapter.navigate_to_filing(page)
        popup.wait_for_selector("text=选择受理法院", timeout=30000)
        popup.wait_for_timeout(2000)

        print('=== 切换到广东省 ===')
        popup.evaluate(SWITCH_JS, '440000')
        popup.wait_for_timeout(4000)
        d = popup.evaluate(DUMP_CITY_JS)
        print('cityList 前5个完整对象:')
        for c in d['cityList_full'][:5]:
            print(' ', c)
        print('fyList:', d['fyList'])

        print('=== 选择广州市并调用 getFyList ===')
        print(popup.evaluate(CITY_JS, '广州'))
        popup.wait_for_timeout(4000)
        d2 = popup.evaluate(DUMP_CITY_JS)
        print('citymc:', d2['citymc'])
        print('fyList:', d2['fyList'][:15], '共', len(d2['fyList']))

        browser.close()
    print('PROBE DONE')


if __name__ == '__main__':
    main()
