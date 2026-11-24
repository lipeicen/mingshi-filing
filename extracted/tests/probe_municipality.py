#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测天津/上海（直辖市）切换后的 cityList / fyList 实际内容。"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'src'))

from playwright.sync_api import sync_playwright
from test_filing_flow import prepare_login_state, STATE_PATH
from adapters.beijing_court import BeijingCourtAdapter

SWITCH_JS = r"""(args) => {
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
    uni.setStorageSync('provinceId', args.pid);
    if (header) {
        const idx = (header.provinces || []).indexOf(args.pid);
        header.currentAreaIndex = idx > 0 ? idx : 1;
    }
    x.value = args.pid;
    x.citymc = ''; x.fyId = ''; x.fymc = ''; x.currentIndex = 0; x.chooseValue = 0;
    x.fyList = [];
    if (typeof x.getCityList === 'function') x.getCityList();
    x.$forceUpdate();
    return 'ok';
}"""

CITY_JS = r"""() => {
    function find(v, tagName) {
        if (!v) return null;
        const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);
        if (tag === tagName) return v;
        for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }
        return null;
    }
    const x = find(document.querySelector('uni-app').__vue__, 'xzfy');
    const cities = (x.cityList || []).filter(c => c && c.citymc);
    if (cities.length) {
        let city = cities.find(c => c.isgy === '2') || cities[0];
        x.citymc = city.citymc;
        // 抓包结论：getFyList 参数为城市名字符串，传对象/ID 会清空 fyList
        try { x.getFyList(city.citymc); } catch (e) {}
        x.$forceUpdate();
        return {city: city.citymc, cities: cities.map(c => c.citymc)};
    }
    return {note: 'no city level'};
}"""

DUMP_JS = r"""() => {
    function find(v, tagName) {
        if (!v) return null;
        const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);
        if (tag === tagName) return v;
        for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }
        return null;
    }
    const x = find(document.querySelector('uni-app').__vue__, 'xzfy');
    return {
        value: x.value, citymc: x.citymc,
        fyList: (x.fyList || []).map(f => f.text), fyList_len: (x.fyList || []).length,
    };
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

        for pid, name in [('120000', '天津'), ('310000', '上海')]:
            print(f'=== {name} ===')
            popup.evaluate(SWITCH_JS, {'pid': pid})
            popup.wait_for_timeout(3000)
            print('city 选择:', popup.evaluate(CITY_JS))
            popup.wait_for_timeout(4000)
            d = popup.evaluate(DUMP_JS)
            print(f"citymc={d['citymc']} fyList({d['fyList_len']}):", d['fyList'][:30])

        browser.close()
    print('PROBE DONE')


if __name__ == '__main__':
    main()
