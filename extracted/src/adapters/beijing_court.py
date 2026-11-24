from loguru import logger

from .base import CourtAdapter

from utils.captcha_solver import CaptchaSolver

import os, time, json, re

from pathlib import Path

from playwright.sync_api import Page, BrowserContext

import re

class BeijingCourtAdapter(CourtAdapter):

    """人民法院在线服务网(北京)民事一审自动立案适配器"""

    PROVINCE_ID = "110000"

    # 省份名称 -> 行政区划代码（与网站 commonHeader.provinces 一致）
    PROVINCE_NAME_TO_ID = {
        '北京': '110000', '天津': '120000', '河北': '130000', '山西': '140000', '内蒙古': '150000',
        '辽宁': '210000', '吉林': '220000', '黑龙江': '230000', '上海': '310000', '江苏': '320000',
        '浙江': '330000', '安徽': '340000', '福建': '350000', '江西': '360000', '山东': '370000',
        '河南': '410000', '湖北': '420000', '湖南': '430000', '广东': '440000', '广西': '450000',
        '海南': '460000', '重庆': '500000', '四川': '510000', '贵州': '520000', '云南': '530000',
        '西藏': '540000', '陕西': '610000', '甘肃': '620000', '青海': '630000', '宁夏': '640000',
        '新疆': '650000', '兵团': '660000', '新疆生产建设兵团': '660000',
    }
    # 直辖市/省直辖：无城市层级，fyList 直接列全省法院
    MUNICIPALITY_IDS = {'110000', '120000', '310000', '500000'}

    @classmethod
    def province_id_from_name(cls, name: str) -> str:
        """省份名称（北京/广东省/内蒙古自治区等写法均可）-> 行政区划代码，未知回退北京"""
        n = re.sub(r'(壮族自治区|回族自治区|维吾尔自治区|自治区|省|市)$', '', str(name or '').strip())
        return cls.PROVINCE_NAME_TO_ID.get(n, cls.PROVINCE_ID)

    @property

    def court_name(self) -> str:

        return "人民法院在线服务"

    @property

    def court_code(self) -> str:

        return "beijing"

    @property

    def base_url(self) -> str:

        return "https://zxfw.court.gov.cn"

    def __init__(self):

        self.save_dir = Path("screenshots/probe")

        self.save_dir.mkdir(parents=True, exist_ok=True)

        self.popup = None

        self.main_page = None

    def _wait(self, t=1.0):

        time.sleep(t)

    def _save_state(self, page: Page, name: str):

        try:

            html_path = self.save_dir / f"{name}.html"

            png_path = self.save_dir / f"{name}.png"

            with open(html_path, 'w', encoding='utf-8') as f:

                f.write(page.content())

            try:

                page.screenshot(path=str(png_path), timeout=5000)

            except Exception as e2:

                logger.warning(f"screenshot {name} skipped: {e2}")

            logger.debug(f"saved state {name}")

        except Exception as e:

            logger.error(f"save state {name} failed: {e}")

    def _click_text(self, page: Page, text: str, timeout=5000, exact=False) -> bool:

        """优先使用 Playwright 文本选择器点击，失败再回退到 JS"""

        for fn in [

            lambda: page.get_by_text(text, exact=exact).click(timeout=timeout),

            lambda: page.click(f"text={text}", timeout=timeout),

            lambda: page.evaluate(

                """(text) => {

                    const all = document.querySelectorAll('*');

                    for (const el of all) if (el.textContent && el.textContent.trim() === text) { el.click(); return true; }

                    return false;

                }""", text

            ),

        ]:

            try:

                fn()

                self._wait(0.5)

                return True

            except Exception:

                pass

        return False

    def _find_page_vue(self, page: Page, tag_name: str):

        """在页面 Vue 组件树中查找指定名称的组件实例"""

        return page.evaluate(

            """(tagName) => {

                const app = document.querySelector('uni-app');

                if (!app) return {err: 'no uni-app'};

                const root = app.__vue__;

                function find(v) {

                    if (!v) return null;

                    const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                    if (tag === tagName) return v;

                    for (const c of v.$children || []) { const r = find(c); if (r) return r; }

                    return null;

                }

                const comp = find(root);

                return comp ? {found: true} : {err: 'not found'};

            }""", tag_name

        )

    def _set_province(self, page: Page, province: str = '北京'):

        """在案件类型选择页切换省份：直接操作 commonHeader 与 Vue 状态"""

        province_id = self.province_id_from_name(province)

        logger.info(f"设置省份为 {province or '北京'} ({province_id})")

        page.evaluate(

            """(provinceId) => {

                const app = document.querySelector('uni-app').__vue__;

                function find(v, tagName) {

                    if (!v) return null;

                    const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                    if (tag === tagName) return v;

                    for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }

                    return null;

                }

                // 1) 更新头部组件省份索引

                const header = find(app, 'commonHeader');

                if (header) {

                    const idx = (header.provinces || []).indexOf(provinceId);

                    header.currentAreaIndex = idx > 0 ? idx : 1;

                    if (typeof header.updateHeaderStorage === 'function') header.updateHeaderStorage();

                }

                // 2) 同步案件类型页(如果有)

                const pick = find(app, 'pagesWsla-pc-zxla-pick-case-type-index');

                if (pick && typeof pick.getListData === 'function') {

                    try { pick.getListData(); } catch (e) {}

                }

                uni.setStorageSync('provinceId', provinceId);

                return 'done';

            }""", province_id

        )

        self._wait(2.5)

    def _set_province_beijing(self, page: Page):
        """兼容旧调用：切到北京"""
        self._set_province(page, '北京')

    def login(self, page: Page, credentials: dict, max_retry: int = 3) -> bool:

        self.main_page = page

        username = credentials.get("username", "")

        password = credentials.get("password", "")

        for attempt in range(1, max_retry + 1):

            logger.debug(f"login attempt {attempt}")

            page.goto(f"{self.base_url}/zxfw/#/pagesGrxx/pc/login/index", wait_until="domcontentloaded")

            self._wait(3)

            self._click_text(page, "律师用户", timeout=3000)

            self._wait(0.5)

            self._click_text(page, "密码登录", timeout=3000)

            self._wait(1)

            try:

                page.wait_for_selector("input[type='password']", timeout=5000)

            except Exception:

                self._click_text(page, "密码登录", timeout=3000)

                self._wait(1)

            inputs = page.query_selector_all(".uni-input-input")

            if len(inputs) >= 2:

                inputs[0].fill(username)

                inputs[1].fill(password)

            if len(inputs) >= 3:

                try:

                    # find captcha image (class fd-images-code or inside fd-captcha)

                    captcha_img = None

                    candidates = page.query_selector_all("img")

                    for img in candidates:

                        cls = img.evaluate("el => el.className") or ""

                        if "fd-images-code" in cls or "captcha" in cls:

                            captcha_img = img

                            break

                    if not captcha_img:

                        # fallback to first image in .fd-captcha

                        captcha_img = page.locator(".fd-captcha img, .fd-images-code").first

                    if captcha_img:

                        # capture data URL or screenshot

                        data_url = captcha_img.evaluate("""el => {

                            if (el.src && el.src.startsWith('data:')) return el.src;

                            return null;

                        }""")

                        if data_url:

                            import base64

                            header, b64 = data_url.split(',', 1)

                            image_bytes = base64.b64decode(b64)

                        else:

                            image_bytes = captcha_img.screenshot()

                        code = CaptchaSolver().solve_image_captcha(image_bytes)

                        inputs[2].fill(code)

                except Exception as e:

                    logger.warning(f"captcha handling skipped: {e}")

            try:

                page.click(".fd-login-btn", timeout=5000)

            except Exception:

                try:

                    page.click("text=登录", timeout=5000)

                except Exception as e:

                    logger.warning(f"click login failed: {e}")

            self._wait(5)

            content = page.content()

            if "在线立案" in content and "密码登录" not in content:

                logger.info("login ok")

                self._save_state(page, "login_success")

                return True

            logger.warning(f"login failed, url {page.url}")

            self._save_state(page, f"login_failed_{attempt}")

        return False

    def navigate_to_filing(self, page: Page, province: str = '北京') -> Page:

        """导航到民事一审立案表单页面，返回新打开的页面实例。

        province: 案件对应省份（决定案件类型页与后续立案页归属的省级平台）"""

        logger.info(f"导航到民事一审立案页面（省份: {province or '北京'}）")

        self._click_text(page, "在线立案")

        self._wait(3)

        self._click_text(page, "我要立案")

        self._wait(3)

        self._save_state(page, "pick_case_type")

        self._set_province(page, province)

        self._save_state(page, "pick_case_type_after_province")

        # 点击“民事一审”会在新窗口打开 wsla/index

        # Wait for page to fully load
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Debug: dump page text
        try:
            page_text = page.evaluate("() => document.body.innerText.slice(0, 500)")
            logger.info(f"Page text before clicking 民事一审: {page_text}")
        except:
            pass

        clicked_ms1s = True
        if not self._click_text(page, "民事一审", timeout=10000, exact=True):
            # Try alternative selectors
            clicked_ms1s = False
            try:
                btn = page.locator('uni-button:has-text("民事一审"), button:has-text("民事一审")').first
                if btn.count() > 0:
                    btn.click(timeout=5000)
                    clicked_ms1s = True
                    logger.info("Clicked 民事一审 via alternative selector")
            except Exception as e:
                logger.warning(f"点击民事一审失败: {e}")

        self._wait(2)

        # 兼容：新窗口 / 当前页跳转 / hash 路由

        new_page = None

        for pg in page.context.pages:

            if "wsla/index" in pg.url or "wsla" in pg.url:

                new_page = pg

                break

        if not new_page and "wsla" in page.url:

            new_page = page

        if not new_page:

            try:

                new_page = page.context.wait_for_event("page", timeout=10000)

                logger.debug(f"new page opened: {new_page.url}")

            except Exception as e:

                logger.warning(f"wait_for_event page timeout: {e}")

        if not new_page:

            # 案件类型列表可能不再返回"民事一审"（服务端变更），直接打开 wsla 页面

            logger.warning("民事一审窗口未打开，直接访问 wsla 页面 URL")

            page.goto(f"{self.base_url}/zxfw/index.html#/pagesWsla/common/wsla/index"

                      "?ajlx=1501_000001-0301&ajlxMc=%E6%B0%91%E4%BA%8B%E4%B8%80%E5%AE%A1",

                      wait_until="domcontentloaded")

            new_page = page

        # 等待页面加载到选择受理法院

        try:

            new_page.wait_for_selector("text=选择受理法院", timeout=30000)

        except Exception as e:

            logger.warning(f"等待选择受理法院超时: {e}")

        self.popup = new_page

        self._save_state(new_page, "civil_first")

        return new_page

    def fill_case_form(self, page: Page, case_data: dict) -> None:

        logger.info("开始填写案件信息...")

        self._select_court(page, case_data)

        self._agree_notice(page)

        self._select_case_cause(page, case_data)

        self._save_state(page, "form_filling")

        # Check if we're in 已准备诉状 flow and need to upload 起诉状 separately

        try:

            page.wait_for_selector("text=上传起诉状", timeout=5000)

            logger.info("检测到上传起诉状页面")

            # Upload 起诉状 here

            if case_data.get('documents'):

                for doc in case_data['documents']:

                    if doc.get('doc_type') == '起诉状' or '起诉状' in doc.get('name', ''):

                        doc_path = doc.get('path')

                        if doc_path and os.path.exists(doc_path):

                            # Find file input and upload

                            file_input = page.locator('input[type="file"]').first

                            if file_input.count() > 0:

                                file_input.set_input_files(doc_path)

                                logger.info(f"上传起诉状: {doc_path}")

                                page.wait_for_timeout(3000)

                                # Click next

                                self._click_page_bottom_next(page)

                                break

        except Exception as e:

            logger.info(f"未检测到上传起诉状页面: {e}")

    def _find_vue_component(self, page: Page, tag_name: str):

        """在页面 Vue 树中查找组件实例"""

        return page.evaluate(

            """(tagName) => {

                const app = document.querySelector('uni-app');

                if (!app || !app.__vue__) return {err: 'no vue'};

                function find(v) {

                    if (!v) return null;

                    const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                    if (tag === tagName) return v;

                    for (const c of v.$children || []) { const r = find(c); if (r) return r; }

                    return null;

                }

                const comp = find(app.__vue__);

                return comp ? {found: true} : {err: 'not found'};

            }""", tag_name

        )

    def _set_xzfy_province(self, page: Page, province: str = '北京', court_name: str = ''):

        """在 wsla/index 选择受理法院页，把 xzfy 组件切到指定省份并加载法院列表。

        普通省份有城市层级：切换省份后需按法院名推导城市、设置 citymc 并调用

        getFyList 加载全省法院；直辖市无城市层级，getCityList 后 fyList 即完整。"""

        province_id = self.province_id_from_name(province)

        logger.info(f"切换受理法院页省份为 {province or '北京'} ({province_id})")

        page.evaluate(

            """(args) => {

                function find(v, tagName) {

                    if (!v) return null;

                    const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                    if (tag === tagName) return v;

                    for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }

                    return null;

                }

                const app = document.querySelector('uni-app').__vue__;

                // 1) 持久化省份，后续接口都依赖

                uni.setStorageSync('provinceId', args.provinceId);

                // 2) 同步 commonHeader 省份索引

                const header = find(app, 'commonHeader');

                if (header) {

                    const idx = (header.provinces || []).indexOf(args.provinceId);

                    header.currentAreaIndex = idx > 0 ? idx : 1;

                }

                // 3) 触发 xzfy 城市列表刷新

                const x = find(app, 'xzfy');

                if (!x) return {err: 'no xzfy'};

                x.value = args.provinceId;

                x.citymc = '';

                x.fyId = '';

                x.fymc = '';

                x.currentIndex = 0;

                x.chooseValue = 0;

                x.fyList = [];

                if (typeof x.getCityList === 'function') x.getCityList();

                x.$forceUpdate();

                return 'ok';

            }""", {'provinceId': province_id}

        )

        self._wait(3)

        # 普通省份：按法院名推导城市并加载该省法院列表

        r = page.evaluate(

            """(args) => {

                function find(v, tagName) {

                    if (!v) return null;

                    const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                    if (tag === tagName) return v;

                    for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }

                    return null;

                }

                const app = document.querySelector('uni-app').__vue__;

                const x = find(app, 'xzfy');

                if (!x) return {err: 'no xzfy'};

                const cities = (x.cityList || []).filter(c => c && c.citymc);

                if (!cities.length) return {ok: true, note: 'no city level'};

                let city = cities.find(c => args.courtName && args.courtName.includes(c.citymc));

                if (!city) city = cities.find(c => c.isgy === '2') || cities[1] || cities[0];

                if (!city) return {ok: true, note: 'no city matched'};

                x.citymc = city.citymc;

                // 抓包确认：getFyList 的 city 参数必须是城市名字符串

                // （fy?sfid=省&id&city=城市名&fymc=）；传对象会序列化成 JSON 串

                // 导致返回空列表并覆盖 fyList

                try { x.getFyList(city.citymc); } catch (e) {}

                x.$forceUpdate();

                return {ok: true, city: city.citymc};

            }""", {'courtName': court_name or ''}

        )

        logger.info(f"xzfy 城市/法院列表加载: {r}")

        self._wait(4)

        # 校验目标法院是否已在列表中；不在则刷新页面让组件按已持久化的省份

        # 自行初始化（天津/上海等必须如此），刷新后普通省份再补一次城市级加载

        def _fy_state():
            return page.evaluate(

                """(courtName) => {

                    function find(v, tagName) {

                        if (!v) return null;

                        const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                        if (tag === tagName) return v;

                        for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }

                        return null;

                    }

                    const x = find(document.querySelector('uni-app').__vue__, 'xzfy');

                    if (!x) return {n: 0, hit: false};

                    const texts = (x.fyList || []).map(f => f.text || '');

                    const hit = courtName ? texts.some(t => courtName.includes(t) || t.includes(courtName)) : texts.length > 2;

                    return {n: texts.length, hit};

                }""", court_name or ''

            )

        def _poll_hit(tries=15, interval=1.5):
            """轮询等待法院列表加载（接口延迟有波动，固定等待不可靠）"""
            st = _fy_state()
            for _ in range(tries):
                if st.get('hit'):
                    break
                self._wait(interval)
                st = _fy_state()
            return st

        state = _poll_hit()

        if not state.get('hit'):

            logger.info(f"目标法院未在列表中（fyList={state.get('n')} 条），刷新页面让组件自行初始化")

            page.reload(wait_until='domcontentloaded')

            self._wait(6)

            state = _fy_state()

            if not state.get('hit'):

                # 刷新后普通省份通常只有省高院，需要重新做城市级加载

                r2 = page.evaluate(

                    """(args) => {

                        function find(v, tagName) {

                            if (!v) return null;

                            const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                            if (tag === tagName) return v;

                            for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }

                            return null;

                        }

                        const x = find(document.querySelector('uni-app').__vue__, 'xzfy');

                        if (!x) return {err: 'no xzfy'};

                        const cities = (x.cityList || []).filter(c => c && c.citymc);

                        if (!cities.length) return {ok: true, note: 'no city level'};

                        let city = cities.find(c => args.courtName && args.courtName.includes(c.citymc));

                        if (!city) city = cities.find(c => c.isgy === '2') || cities[1] || cities[0];

                        if (!city) return {ok: true, note: 'no city matched'};

                        x.citymc = city.citymc;

                        // 抓包确认：getFyList 参数为城市名字符串，传对象会清空 fyList
                        try { x.getFyList(city.citymc); } catch (e) {}

                        x.$forceUpdate();

                        return {ok: true, city: city.citymc};

                    }""", {'courtName': court_name or ''}

                )

                logger.info(f"刷新后重新加载城市法院: {r2}")

                state = _poll_hit()

                logger.info(f"刷新后法院列表状态: {state}")

    def _set_xzfy_beijing(self, page: Page):
        """兼容旧调用：切到北京"""
        self._set_xzfy_province(page, '北京')

    def _click_court_card(self, page: Page, court_name: str) -> bool:

        """通过操作 Vue 状态选择法院(uni-app 渲染的 radio label 点击不触发响应)。

        匹配容忍省份/城市前缀差异：如 fyList 里叫「浙江省杭州市西湖区人民法院」，

        传入「杭州市西湖区人民法院」也能命中。"""

        if not court_name:

            return False

        # 生成候选名：全称、去省前缀、再去市前缀

        candidates = [court_name]

        short = re.sub(r'^.*?(省|自治区)', '', court_name)

        if short and short != court_name:

            candidates.append(short)

        shorter = re.sub(r'^.*?市', '', short)

        if shorter and shorter != short:

            candidates.append(shorter)

        selected = page.evaluate(

            """(names) => {

                function find(v, tagName) {

                    if (!v) return null;

                    const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                    if (tag === tagName) return v;

                    for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }

                    return null;

                }

                const app = document.querySelector('uni-app').__vue__;

                const x = find(app, 'xzfy');

                if (!x || !x.fyList) return {err: 'no xzfy or fyList'};

                for (let i = 0; i < x.fyList.length; i++) {

                    const fy = x.fyList[i];

                    if (!fy.text) continue;

                    if (!names.some(n => fy.text.includes(n))) continue;

                    x.fyId = String(fy.value);

                    x.fymc = fy.text;

                    x.currentIndex = String(fy.value);

                    x.chooseValue = fy.value;

                    x.$forceUpdate();

                    return {ok: true, court: fy.text, value: fy.value};

                }

                return {err: 'court not found in fyList', name: names[0], fyListLen: x.fyList.length};

            }""", candidates

        )

        self._wait(0.5)

        if selected.get('ok'):

            logger.debug(f"selected court by state: {selected.get('court')}")

            return True

        logger.warning(f"select court failed: {selected}")

        return False

    def _select_court(self, page: Page, case_data: dict):

        logger.info("选择受理法院...")

        try:

            page.wait_for_selector("text=选择受理法院", timeout=30000)

        except Exception:

            pass

        self._save_state(page, "court_select")

        # 关键：先切换到案件对应省份（默认北京），并清空旧选择

        target_court = case_data.get("court_name", "")

        province = case_data.get("court_province", "") or "北京"

        self._set_xzfy_province(page, province, target_court)

        self._save_state(page, "court_select_province")

        if target_court:

            # 部分省份法院列表加载较慢，未命中时等待重试

            court_ok = False

            for attempt in range(3):

                if self._click_court_card(page, target_court):

                    court_ok = True

                    break

                logger.info(f"法院选择第 {attempt + 1} 次未命中，等待列表加载后重试")

                self._wait(3)

            if not court_ok:

                logger.warning(f"未选择到指定法院: {target_court}")

        else:

            # 默认选择第一个基层法院(排除中级/高级/最高/海事/知识产权/金融/互联网/铁路)

            selected = page.evaluate(

                """() => {

                    function findXzfy(v) {

                        if (!v) return null;

                        const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                        if (tag === 'xzfy') return v;

                        for (const c of v.$children || []) { const r = findXzfy(c); if (r) return r; }

                        return null;

                    }

                    const x = findXzfy(document.querySelector('uni-app').__vue__);

                    if (x && x.fyList) {

                        for (const fy of x.fyList) {

                            const txt = fy.text || '';

                            if (/高级|最高|中级|海事|知识产权|金融|互联网|铁路/.test(txt)) continue;

                            if (txt.includes('人民法院')) {

                                x.fyId = String(fy.value);

                                x.fymc = txt;

                                x.currentIndex = String(fy.value);

                                x.chooseValue = fy.value;

                                x.$forceUpdate();

                                return txt;

                            }

                        }

                    }

                    return null;

                }"""

            )

            logger.debug(f"auto selected court: {selected}")

            self._wait(0.5)

        self._save_state(page, "after_court_selected")

        # 选择“为他人或公司等组织申请”，避免申请人自动填充为登录人姓名

        self._click_text(page, "为他人或公司等组织申请", timeout=5000)

        self._wait(0.5)

        # 关闭可能弹出的提示层(综治中心等)

        for btn_text in ["关闭", "我知道了", "不再提醒"]:

            self._click_text(page, btn_text, timeout=3000)

        self._wait(0.5)

        # 点击下一步：真实点击失败时直接调用组件 nextStep

        next_clicked = False

        if not self._click_text(page, "下一步", timeout=5000):

            try:

                page.click("uni-button[type='primary']", timeout=3000)

                next_clicked = True

            except Exception as e:

                logger.warning(f"下一步点击失败: {e}")

        else:

            next_clicked = True

        if not next_clicked:

            try:

                page.evaluate(

                    """() => {

                        function find(v, tagName) {

                            if (!v) return null;

                            const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                            if (tag === tagName) return v;

                            for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }

                            return null;

                        }

                        const x = find(document.querySelector('uni-app').__vue__, 'xzfy');

                        if (x && typeof x.nextStep === 'function') { x.nextStep(); return 'nextStep called'; }

                        return 'no nextStep';

                    }"""

                )

            except Exception as e:

                logger.warning(f"nextStep 调用失败: {e}")

        self._wait(3)

        self._save_state(page, "after_court_next")

    def _agree_notice(self, page: Page):

        logger.info("阅读须知...")

        try:

            page.wait_for_selector("text=立案须知", timeout=10000)

        except Exception:

            pass

        try:

            self._save_state(page, "notice")

        except Exception as e:

            logger.warning(f"notice state save skipped: {e}")

        # 勾选“已阅读同意立案须知内容”

        for agree_text in ["已阅读同意立案须知内容", "已阅读同意", "已阅读并同意"]:

            try:

                agree = page.locator(f"text={agree_text}")

                if agree.count():

                    agree.click()

                    self._wait(0.5)

                    break

            except Exception:

                pass

        else:

            try:

                cb = page.locator(".uni-checkbox-input").first

                if cb.count():

                    cb.click()

                    self._wait(0.5)

            except Exception as e:

                logger.warning(f"勾选同意失败: {e}")

        # 点击下一步，并处理连续弹窗

        try:

            page.locator("uni-button").filter(has_text="下一步").click(timeout=5000)

        except Exception:

            self._click_text(page, "下一步", timeout=5000)

        self._wait(2)

        try:

            self._save_state(page, "notice_next")

        except Exception as e:

            logger.warning(f"notice_next state save skipped: {e}")

        # 处理要素式/智能识别弹窗 + 立案方式选择

        for i in range(5):

            handled = False

            # 1) 优先关闭“要素式立案”提示

            for btn in ["不选择要素式立案", "不体验智能识别要素式立案服务"]:

                try:

                    loc = page.locator("uni-button").filter(has_text=btn)

                    if loc.count() and loc.first.is_visible():

                        loc.first.click(timeout=3000)

                        logger.debug(f"弹窗按钮: {btn}")

                        handled = True

                        self._wait(2)

                        break

                except Exception:

                    continue

            if handled:

                try:

                    self._save_state(page, f"notice_popup_{i}")

                except Exception as e:

                    logger.warning(f"notice_popup_{i} state save skipped: {e}")

                continue

# 2) 选择立案方式：优先"已准备诉状"

            if self._has_text(page, "请选择立案方式"):

                # 优先选择"已准备诉状"

                try:

                    loc = page.locator("text=已准备诉状").first

                    if loc.is_visible():

                        loc.click(timeout=5000)

                        logger.info("选择立案方式: 已准备诉状")

                        self._wait(2)

                        handled = True

                        try:

                            self._save_state(page, f"notice_popup_{i}")

                        except Exception as e:

                            logger.warning(f"notice_popup_{i} state save skipped: {e}")

                        break

                except Exception as e:

                    logger.warning(f"选择已准备诉状失败: {e}")

                # 兜底选择"未准备诉状"

                try:

                    loc = page.locator("text=未准备诉状").first

                    if loc.is_visible():

                        loc.click(timeout=5000)

                        logger.info("选择立案方式: 未准备诉状")

                        self._wait(2)

                        handled = True

                        try:

                            self._save_state(page, f"notice_popup_{i}")

                        except Exception as e:

                            logger.warning(f"notice_popup_{i} state save skipped: {e}")

                        break

                except Exception as e:

                    logger.warning(f"选择未准备诉状失败: {e}")

                break

        # 若仍停留在须知页面，再次点击下一步

        if (self._has_text(page, "立案须知") and self._has_text(page, "下一步")

                and not self._has_text(page, "选择立案案由")):

            try:

                page.locator("uni-button").filter(has_text="下一步").click(timeout=5000)

            except Exception:

                self._click_text(page, "下一步", timeout=5000)

            self._wait(2)

        self._save_state(page, "notice_after_popup")

    def _has_text(self, page: Page, text: str) -> bool:

        try:

            return page.locator(f"text={text}").count() > 0

        except Exception:

            return False

    def _get_active_step_text(self, page: Page) -> str:

        """获取顶部进度条当前高亮步骤文本(uni-steps 通过蓝色+加粗样式判断)"""

        try:

            # 优先匹配 uni-steps 里当前激活步骤：style 含 rgb(0, 150, 255) 且 font-weight: 700

            result = page.evaluate("""() => {

                const titles = document.querySelectorAll('.uni-steps__row-title');

                for (const t of titles) {

                    const style = t.getAttribute('style') || '';

                    if (style.includes('rgb(0, 150, 255)') && style.includes('700')) {

                        return (t.innerText || '').trim();

                    }

                }

                return '';

            }""")

            if result:

                return result

        except Exception as e:

            logger.debug(f"_get_active_step_text evaluate failed: {e}")

        try:

            active = page.locator('.fd-com-step-item--active, .fd-step-item--active, .step-item--active, .active').first

            if active.count():

                return (active.inner_text() or '').strip()[:20]

        except Exception:

            pass

        return ""

    def _is_on_success_page(self, page: Page) -> bool:

        """判断是否真的到了提交成功页(而不是进度条标签)"""

        content = page.content()

        # Primary check: must have success indicator

        success_keywords = ["提交成功", "立案成功", "申请成功", "提交完毕", "立案申请已提交"]

        has_success_text = any(kw in content for kw in success_keywords)

        if not has_success_text:

            return False

        # Exclude if still on form pages (has prev/next navigation)

        if page.locator("button:has-text('上一步'), uni-button:has-text('上一步')").count() > 0:

            return False

        if page.locator("button:has-text('下一步'), uni-button:has-text('下一步')").count() > 0:

            return False

        # Positive indicators of success page

        success_indicators = [

            "button:has-text('返回')", "uni-button:has-text('返回')",

            "button:has-text('返回首页')", "uni-button:has-text('返回首页')",

            "button:has-text('查看案件')", "uni-button:has-text('查看案件')",

            "button:has-text('查看进度')", "uni-button:has-text('查看进度')",

            "button:has-text('继续立案')", "uni-button:has-text('继续立案')",

        ]

        for indicator in success_indicators:

            try:

                if page.locator(indicator).count() > 0:

                    return True

            except:

                continue

        # Check for case number display (strong success indicator)

        try:

            page_text = page.evaluate("() => document.body.innerText")

            if re.search(r'[((]\d{4}[))]\S+?号', page_text):

                return True

        except:

            pass

        # 兜底：顶部进度条当前步骤为"提交成功"且无返回按钮时也算成功

        active = self._get_active_step_text(page)

        if active in ("提交成功", "完成", "立案成功"):

            # Double-check: must NOT have form submission buttons

            if page.locator("button:has-text('提交'), uni-button:has-text('提交')").count() == 0:

                return True

        # Strict check: NOT success if we still have form navigation

        # Note: network timeout popup is transient and doesn't block actual submission success

        try:

            page_text = page.evaluate("() => document.body.innerText")

            # Only reject if network error AND no success text (but we already checked success text above)

            # Network timeout popup can appear even after successful submission

            if '上一步' in page_text and '提交' in page_text:

                return False

        except:

            pass

        return True  # Has success text, no form nav => success page even with transient popups

    def _select_case_cause(self, page: Page, case_data: dict):

        logger.info("选择立案案由/法院...")

        # 1) 处理“选择立案方式”弹层/页面(未准备诉状 / 已准备诉状)

        try:

            page.wait_for_selector("text=请选择立案方式", timeout=10000)

            logger.info("选择立案方式: 已准备诉状")

            page.locator("text=已准备诉状").first.click(timeout=5000)

            self._wait(5)

            # Verify the selection took effect

            page_text = page.evaluate("() => document.body.innerText")

            if '已准备诉状' in page_text:

                logger.info("已准备诉状 选择成功")

            else:

                logger.warning("已准备诉状 选择可能未生效")

        except Exception:

            logger.info("未出现选择立案方式页面")

        # 2) 等待案由选择页

        try:

            page.wait_for_selector("text=选择立案案由", timeout=10000)

        except Exception:

            pass

        self._save_state(page, "case_cause")

        # 3) 选择具体法院(单选)

        court_name = case_data.get("court_name") or getattr(self, "court_name", "")

        if court_name:

            try:

                court_label = page.locator('uni-label, label, uni-view, view').filter(has_text=re.compile(re.escape(court_name))).first

                if court_label.count() and court_label.is_visible(timeout=3000):

                    court_label.click(timeout=5000)

                    logger.info(f"选择法院: {court_name}")

                    self._wait(1)

                else:

                    res = page.evaluate("""(courtName) => {

                        const labels = Array.from(document.querySelectorAll('uni-label, label, uni-view, view'));

                        const lbl = labels.find(el => (el.innerText||'').trim().includes(courtName));

                        if (!lbl) return {err: 'label not found'};

                        lbl.click();

                        return {ok: true};

                    }""", court_name)

                    logger.info(f"JS选择法院: {court_name} -> {res}")

            except Exception as e:

                logger.warning(f"选择法院失败: {e}")

        # 4) 申请人类型(默认 本人申请)

        try:

            applicant_type = case_data.get("applicant_type", "为他人或公司等组织申请")

            type_label = page.locator('uni-label, label').filter(has_text=re.compile(applicant_type)).first

            if type_label.count() and type_label.is_visible(timeout=2000):

                type_label.click(timeout=3000)

                logger.info(f"选择申请人类型: {applicant_type}")

        except Exception as e:

            logger.debug(f"申请人类型选择忽略: {e}")

        self._wait(1)

        self._save_state(page, "court_selected")

        # 5) 案由选择：优先使用 uni-data-tree 级联选择器（wsla 页面实际结构），
        #    未命中再回退到旧版搜索框流程

        cause_keyword = case_data.get("case_reason") or case_data.get("metadata", {}).get("case_cause", "") or "买卖合同纠纷"

        cause_selected = False

        for tree_round in range(3):

            try:

                page.wait_for_selector('.uni-data-tree', state='visible', timeout=8000)

            except Exception:

                logger.info(f"案由级联选择器第 {tree_round+1} 轮等待 .uni-data-tree 超时")

            if self._select_cause_from_tree(page, cause_keyword):

                cause_selected = True

                break

            page.wait_for_timeout(1500)

        if cause_selected:

            logger.info(f"案由已通过级联选择器选中: {cause_keyword}")

        else:

            logger.info("案由级联选择器未命中，回退旧版搜索流程")

            try:

                res = page.evaluate(r"""(args) => {

                    const keyword = args.keyword;

                    function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

                    const inputs = Array.from(document.querySelectorAll('input.uni-input-input, input[type="text"], uni-input input')).filter(isVisible);

                    const inp = inputs.find(i => (i.placeholder || '').includes('搜索') || (i.placeholder || '').includes('关键词') || (i.placeholder || '').includes('案由')) || inputs[0];

                    if (!inp) return {err: 'no input'};

                    inp.value = keyword;

                    inp.dispatchEvent(new Event('input', {bubbles: true}));

                    inp.dispatchEvent(new Event('change', {bubbles: true}));

                    return {ok: true};

                }""", {"keyword": cause_keyword})

                logger.debug(f"案由搜索输入: {cause_keyword} -> {res}")

                self._wait(1)

                search_btn = page.locator('uni-button, button').filter(has_text=re.compile('搜索')).first

                if search_btn.count() and search_btn.is_visible(timeout=2000):

                    search_btn.click(timeout=5000)

                    logger.info("点击案由搜索")

                    self._wait(3)

                # 选择第一个匹配结果

                opts = page.locator('uni-view, view, uni-text, text').filter(has_text=re.compile(re.escape(cause_keyword))).all()

                if opts:

                    opts[0].click(timeout=5000)

                    logger.info(f"选择案由结果: {cause_keyword}")

                else:

                    first_opt = page.locator('.uni-data-tree-item, .uni-picker-item, .uni-list-item, uni-view, view').first

                    if first_opt.count() and first_opt.is_visible(timeout=2000):

                        first_opt.click(timeout=3000)

                        logger.info("选择第一个案由结果")

                self._wait(2)

            except Exception as e:

                logger.warning(f"案由搜索失败: {e}")

        self._save_state(page, "case_cause_selected")

        # 6) 下一步(进入上传诉讼材料页面)

        self._click_page_bottom_next(page)

        self._wait(5)

        self._save_state(page, "case_cause_next")


    def _select_cause_from_tree(self, page: Page, keyword: str) -> bool:
        """在“选择立案案由”步骤操作 uni-data-tree 级联选择器完成案由选择。

        页面实际结构（依据 wsla 页面快照确认）：
        - 触发器: .uni-data-tree > .uni-data-tree-input > .input-value
                  （未选时 .selected-area 带 placeholder 类，文本为“请选择”）
        - 弹层:   .uni-data-tree-dialog
                  搜索框 .fd-search-container input.uni-input-input（占位“搜索关键词”）
                  选项列表 .fd-picker-list .fd-item > .item-text
        - 选中后: 弹层关闭，.selected-area 去掉 placeholder 并显示案由全称
        """
        try:
            tree = page.locator('.uni-data-tree').first
            if not tree.count() or not tree.is_visible(timeout=3000):
                return False
        except Exception:
            return False

        for attempt in range(3):
            try:
                # 0) 已经选中则直接成功
                state = page.evaluate("""() => {
                    const t = document.querySelector('.uni-data-tree');
                    if (!t) return {exists: false};
                    const area = t.querySelector('.uni-data-tree-input .selected-area');
                    const dialog = t.querySelector('.uni-data-tree-dialog');
                    const dlgVisible = dialog && dialog.getBoundingClientRect().width > 0;
                    return {
                        exists: true,
                        selected: (area && !area.classList.contains('placeholder')) ? (area.innerText || '').trim() : '',
                        dialogOpen: !!dlgVisible
                    };
                }""")
                if state.get('selected'):
                    logger.info(f"案由已选中: {state['selected']}")
                    return True

                # 1) 打开弹层
                if not state.get('dialogOpen'):
                    trigger = tree.locator('.uni-data-tree-input .input-value').first
                    try:
                        trigger.scroll_into_view_if_needed(timeout=3000)
                    except Exception:
                        pass
                    try:
                        trigger.click(timeout=3000)
                    except Exception:
                        page.evaluate("""() => {
                            const el = document.querySelector('.uni-data-tree .uni-data-tree-input .input-value');
                            if (el) el.click();
                        }""")
                    try:
                        page.wait_for_selector('.uni-data-tree-dialog', state='visible', timeout=5000)
                    except Exception:
                        logger.warning(f"案由弹层未打开（第{attempt + 1}次）")
                        continue

                # 2) 输入搜索关键词
                search = page.locator('.uni-data-tree-dialog .fd-search-container input').first
                if search.count() and search.is_visible(timeout=2000):
                    try:
                        search.click(timeout=2000)
                        search.fill('')
                        search.fill(keyword)
                    except Exception:
                        page.evaluate("""(kw) => {
                            const inp = document.querySelector('.uni-data-tree-dialog .fd-search-container input');
                            if (!inp) return;
                            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                            setter.call(inp, kw);
                            inp.dispatchEvent(new Event('input', {bubbles: true}));
                            inp.dispatchEvent(new Event('change', {bubbles: true}));
                        }""", keyword)
                    page.wait_for_timeout(1500)

                # 3) 点击匹配项（精确匹配优先，否则第一项；级联时循环深入直至选中）
                for _round in range(4):
                    st = page.evaluate("""(kw) => {
                        const t = document.querySelector('.uni-data-tree');
                        if (!t) return {err: 'no tree'};
                        const area = t.querySelector('.uni-data-tree-input .selected-area');
                        const selected = (area && !area.classList.contains('placeholder')) ? (area.innerText || '').trim() : '';
                        const dialog = t.querySelector('.uni-data-tree-dialog');
                        const dlgVisible = dialog && dialog.getBoundingClientRect().width > 0;
                        if (selected) return {done: true, selected: selected};
                        if (!dlgVisible) return {done: false, err: 'dialog closed without selection'};
                        function vis(el) { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }
                        const items = Array.from(dialog.querySelectorAll('.fd-picker-list .fd-item')).filter(vis);
                        if (!items.length) return {done: false, err: 'no items'};
                        const exact = items.find(it => {
                            const x = it.querySelector('.item-text');
                            return x && (x.innerText || '').trim() === kw;
                        });
                        const target = exact || items[0];
                        const text = ((target.querySelector('.item-text') || target).innerText || '').trim();
                        target.scrollIntoView({block: 'center'});
                        target.click();
                        return {done: false, picked: text, exact: !!exact, total: items.length};
                    }""", keyword)
                    logger.info(f"案由选项点击: {st}")
                    if st.get('done'):
                        logger.info(f"案由选择成功: {st.get('selected')}")
                        return True
                    if st.get('err'):
                        break
                    page.wait_for_timeout(1200)

                # 4) 最终校验
                final = page.evaluate("""() => {
                    const area = document.querySelector('.uni-data-tree .uni-data-tree-input .selected-area');
                    return (area && !area.classList.contains('placeholder')) ? (area.innerText || '').trim() : '';
                }""")
                if final:
                    logger.info(f"案由选择成功: {final}")
                    return True
                logger.warning(f"案由选择未生效（第{attempt + 1}次），重试")
            except Exception as e:
                logger.warning(f"案由树选择异常（第{attempt + 1}次）: {e}")
                page.wait_for_timeout(800)
        return False


    def probe_form_structure(self, page: Page, name: str = "form_probe"):

        """保存表单页面结构供分析"""

        try:

            html_path = self.save_dir / f"{name}.html"

            png_path = self.save_dir / f"{name}.png"

            with open(html_path, 'w', encoding='utf-8') as f:

                f.write(page.content())

            page.screenshot(path=str(png_path), full_page=True)

            logger.debug(f"form probe saved: {name}")

        except Exception as e:

            logger.error(f"form probe failed: {e}")

    def _upload_with_retry(self, page, btn, doc_path: str, title: str, max_attempts: int = 3) -> bool:

        """上传文件，带重试和多种 fallback"""

        # Method 1: set_input_files on hidden input

        # Method 1: set_input_files on hidden input

        try:

            file_input = page.locator('input[type="file"]').first

            if file_input.count() > 0:

                file_input.set_input_files(doc_path)

                logger.debug(f"set_input_files {doc_path} for {title}")

                # Trigger change event for Vue

                try:

                    file_input.evaluate("""(input) => {

                        const event = new Event('change', { bubbles: true });

                        input.dispatchEvent(event);

                        const inputEvent = new Event('input', { bubbles: true });

                        input.dispatchEvent(inputEvent);

                    }""")

                except Exception as evt_err:

                    logger.debug(f"Event dispatch failed: {evt_err}")

                self._wait(2)

                return True

        except Exception as e:

            logger.debug(f"set_input_files failed: {e}")

        # Method 2: filechooser with retries

        for attempt in range(max_attempts):

            try:

                with page.expect_event("filechooser", timeout=8000) as fc_info:

                    btn.click(timeout=8000)

                fc = fc_info.value

                fc.set_files(doc_path)

                logger.debug(f"filechooser selected {doc_path} for {title} (attempt {attempt+1})")

                self._wait(2)

                return True

            except Exception as e:

                logger.warning(f"filechooser attempt {attempt+1} failed for {title}: {e}")

                try:

                    page.press('body', 'Escape')

                    self._wait(0.5)

                except Exception:

                    pass

        # Method 3: JS click + filechooser

        try:

            with page.expect_event("filechooser", timeout=8000) as fc_info:

                btn.evaluate("el => el.click()")

            fc = fc_info.value

            fc.set_files(doc_path)

            logger.debug(f"JS-click filechooser selected {doc_path} for {title}")

            self._wait(2)

            return True

        except Exception as e:

            logger.warning(f"JS-click filechooser failed for {title}: {e}")

        return False

    def upload_documents(self, page: Page, documents: list) -> None:

        logger.info("上传案件材料...")

        try:

            page.wait_for_selector("text=上传诉讼材料", timeout=15000)

        except Exception:

            pass

        # Wait for page to fully load

        page.wait_for_timeout(5000)

        # Scroll to load all sections

        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")

        page.wait_for_timeout(2000)

        page.evaluate("() => window.scrollTo(0, 0)")

        page.wait_for_timeout(1000)

        self._save_state(page, "upload_before")

        # Map documents to buckets by category keywords (documents come from CaseDocument.to_dict -> 'type')

        category_map = {

            '起诉状': ['起诉状', '起诉材料'],

            '身份证明': ['身份证明', '当事人身份证明'],

            '证据': ['证据', '证据目录'],

            '委托书': ['委托', '代理人', '授权'],

            '送达地址确认书': ['送达'],

            '其他材料': ['其他'],

        }

        buckets = {}

        for doc in documents:

            doc_path = doc.get('path') if isinstance(doc, dict) else doc.path

            dtype = (doc.get('type') if isinstance(doc, dict) else getattr(doc, 'doc_type', '')) or ''

            matched = False

            for cat, kws in category_map.items():

                if any(k in dtype for k in kws):

                    buckets.setdefault(cat, []).append(doc_path)

                    matched = True

                    break

            if not matched:

                buckets.setdefault('其他材料', []).append(doc_path)

        logger.debug(f"document buckets: {list(buckets.keys())}")

        # Use in-page JS to map each add button to its section title via DOM ancestors

        # Scroll to bottom to load all sections, then scroll back to top

        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")

        page.wait_for_timeout(2000)

        page.evaluate("() => window.scrollTo(0, 0)")

        page.wait_for_timeout(1000)

        button_map = page.evaluate("""() => {

            const out = [];

            const sections = document.querySelectorAll('.uni-section');

            for (const sec of sections) {

                const titleEl = sec.querySelector('.uni-section__content-title');

                const title = titleEl ? (titleEl.textContent || '').trim() : '';

                const btn = sec.querySelector('.fd-file-container.fd-btn-add, .fd-btn-add');

                if (!btn) continue;

                const rect = btn.getBoundingClientRect();

                out.push({title, y: rect.y + rect.height/2, h: rect.height});

            }

            // Also check for any section with 起诉状 or 诉状 in title

            const allTitles = [];

            const allSections = document.querySelectorAll('.uni-section, [class*="section"], [class*="upload"]');

            for (const sec of allSections) {

                const text = sec.textContent || '';

                if (text.includes('起诉状') || text.includes('诉状')) {

                    const title = text.substring(0, 50).trim();

                    allTitles.push(title);

                }

            }

            return {sections: out, qisuzhuangTitles: allTitles};

        }""")

        logger.debug(f"sections_list: {button_map}")

        # Fallback: 未准备诉状页面没有"起诉状"按钮，把起诉状文件归到"其他材料"

        sections_list = button_map.get('sections', []) if isinstance(button_map, dict) else button_map

        if not any(('起诉状' in info['title'] or '诉状' in info['title']) for info in sections_list):

            if '起诉状' in buckets:

                # Try to upload to first available section

                if sections_list:

                    first_title = sections_list[0]['title']

                    logger.info(f"页面无起诉状按钮，将起诉状上传到第一个section: {first_title}")

                    # We'll handle this specially below

                else:

                    buckets.setdefault('其他材料', []).extend(buckets.pop('起诉状'))

                    logger.info("页面无起诉状按钮且无sections，将起诉状归入其他材料")

        # Special handling: upload 起诉状 to first section if no 起诉状 section exists

        has_qisuzhuang_section = any(('起诉状' in info['title'] or '诉状' in info['title']) for info in sections_list)

        if not has_qisuzhuang_section and '起诉状' in buckets and sections_list:

            first_info = sections_list[0]

            first_title = first_info['title']

            qisuzhuang_paths = [p for p in buckets['起诉状'] if os.path.exists(p)]

            if qisuzhuang_paths:

                logger.info(f"上传起诉状到第一个section: {first_title}")

                section = page.locator('.uni-section').filter(has_text=first_title).first

                btn = section.locator('.fd-file-container.fd-btn-add, .fd-btn-add').first

                file_input = None

                try:

                    file_input = section.locator('input[type="file"]').first

                    if file_input.count() == 0:

                        file_input = None

                except Exception:

                    file_input = None

                logger.info(f"开始上传起诉状，文件: {qisuzhuang_paths}")

                logger.debug(f"file_input exists: {file_input is not None}, count: {file_input.count() if file_input else 0}")

                for doc_path in qisuzhuang_paths:

                    uploaded = False

                    logger.info(f"尝试上传: {doc_path}")

                    if file_input and file_input.count():

                        try:

                            file_input.set_input_files(doc_path)

                            logger.debug(f"set_input_files 起诉状 {doc_path}")

                            uploaded = True

                        except Exception as e:

                            logger.warning(f"set_input_files failed: {e}")

                    if not uploaded:

                        try:

                            with page.expect_file_chooser(timeout=5000) as fc_info:

                                btn.click()

                            fc = fc_info.value

                            fc.set_files(doc_path)

                            logger.debug(f"filechooser 起诉状 {doc_path}")

                            uploaded = True

                        except Exception as e:

                            logger.warning(f"filechooser failed: {e}")

                    if uploaded:

                        page.wait_for_timeout(3000)

                        # Verify upload by checking for filename

                        filename = os.path.basename(doc_path)

                        try:

                            # Check if filename appears on page

                            page_text = page.evaluate("() => document.body.innerText")

                            if filename in page_text:

                                logger.info(f"起诉状上传成功，页面显示: {filename}")

                                # Try to find and click a save/confirm button

                                save_selectors = ['text=保存', 'text=确定', 'text=完成', 'text=确认']

                                for sel in save_selectors:

                                    try:

                                        btn = page.locator(sel).first

                                        if btn.count() > 0 and btn.is_visible():

                                            btn.click(timeout=3000)

                                            logger.info(f"点击保存按钮: {sel}")

                                            page.wait_for_timeout(2000)

                                            break

                                    except:

                                        continue

                            else:

                                logger.warning(f"起诉状上传后页面未显示: {filename}")

                                # List all files shown

                                import re

                                file_matches = re.findall(r'[^\s]+\.pdf|[^\s]+\.doc[^\s]*', page_text)

                                logger.info(f"页面显示的文件: {file_matches}")

                        except Exception as e:

                            logger.warning(f"验证上传失败: {e}")

        for i, info in enumerate(sections_list):

            title = info['title']

            logger.debug(f"button {i}: section '{title}'")

            bucket_key = None

            if '起诉状' in title or '诉状' in title:

                bucket_key = '起诉状'

            elif '身份证明' in title:

                bucket_key = '身份证明'

            elif '委托' in title or '代理' in title:

                bucket_key = '委托书'

            elif '证据' in title:

                bucket_key = '证据'

            elif '送达' in title:

                bucket_key = '送达地址确认书'

            elif '其他' in title or '材料信息' in title:

                bucket_key = '其他材料'

            else:

                bucket_key = '其他材料'

            paths = buckets.get(bucket_key, [])

            if not paths:

                logger.debug(f"skip button {i} ({bucket_key}): no documents")

                continue

            existing_paths = [p for p in paths if os.path.exists(p)]

            if not existing_paths:

                logger.warning(f"skip button {i} ({bucket_key}): no existing documents")

                continue

            expected_names = [os.path.basename(p) for p in existing_paths]

            section = page.locator('.uni-section').filter(has_text=title).first

            btn = section.locator('.fd-file-container.fd-btn-add, .fd-btn-add').first

            uploaded_count = 0

            # Use filechooser first (more reliable), set_input_files as fallback

            uploaded_count = 0

            for doc_path in existing_paths:

                uploaded = False

                # Method 1: Use filechooser (click button -> file dialog)

                try:

                    with page.expect_event("filechooser", timeout=8000) as fc_info:

                        btn.click(timeout=8000)

                    fc = fc_info.value

                    fc.set_files(doc_path)

                    logger.debug(f"filechooser uploaded {doc_path} for section {title}")

                    uploaded = True

                    uploaded_count += 1

                    self._wait(3)  # Wait for upload to complete

                except Exception as e:

                    logger.debug(f"filechooser failed for {title}: {e}")

                    try:

                        page.press('body', 'Escape')

                        self._wait(0.5)

                    except:

                        pass

                # Method 2: set_input_files as fallback

                if not uploaded:

                    try:

                        file_input = section.locator('input[type="file"]').first

                        if file_input.count() > 0:

                            file_input.set_input_files(doc_path)

                            logger.debug(f"set_input_files {doc_path} for section {title}")

                            # Trigger change event

                            try:

                                file_input.evaluate("""(input) => {

                                    const event = new Event('change', { bubbles: true });

                                    input.dispatchEvent(event);

                                }""")

                            except:

                                pass

                            uploaded = True

                            uploaded_count += 1

                            self._wait(3)

                    except Exception as e2:

                        logger.warning(f"set_input_files also failed for {title}: {e2}")

                if not uploaded:

                    logger.error(f"最终上传失败: {title} / {doc_path}")

            # Verify expected file names appear in this section

            # Wait a bit more for upload to complete

            self._wait(3)

            try:

                shown_titles = section.locator('.fd-com-upload-grid-container .fd-file-cursor').evaluate_all(

                    """elements => elements.map(e => {

                        const nameEl = e.querySelector('.fd-file-name');

                        const name = nameEl ? (nameEl.innerText || nameEl.textContent || '') : '';

                        const title = e.getAttribute('title') || '';

                        return title || name;

                    })"""

                )

                shown_names = [os.path.basename(t).split('-')[-1] for t in shown_titles if t]

                logger.debug(f"section {title} expected {expected_names}, shown {shown_names}")

                # Check if upload actually succeeded

                if not shown_names and uploaded_count > 0:

                    logger.warning(f"section {title}: uploaded {uploaded_count} files but none shown, retrying...")

                    self._wait(5)

                    try:

                        shown_titles = section.locator('.fd-com-upload-grid-container .fd-file-cursor, .fd-file-name, [class*="file"]').evaluate_all(

                            """elements => elements.map(e => {

                                const nameEl = e.querySelector('.fd-file-name');

                                const name = nameEl ? (nameEl.innerText || nameEl.textContent || '') : '';

                                const title = e.getAttribute('title') || '';

                                return title || name || (e.innerText || '');

                            })"""

                        )

                        shown_names = [os.path.basename(t).split('-')[-1] for t in shown_titles if t]

                        logger.debug(f"section {title} retry: shown {shown_names}")

                    except Exception as e2:

                        logger.warning(f"retry verify section {title} failed: {e2}")

            except Exception as e:

                logger.warning(f"verify section {title} failed: {e}")

        self._save_state(page, "upload_after")

        # 进入完善案件信息：优先使用 Vue nextStep，失败时尝试点击按钮

        next_result = self._vue_click_next(page)

        if not next_result.get('ok'):

            logger.warning(f"Vue nextStep 失败，尝试点击按钮: {next_result}")

            next_result = self._click_page_bottom_next(page)

        try:

            page.wait_for_selector("text=完善案件信息", timeout=15000)

            logger.info("已进入完善案件信息页面")

            self._save_state(page, "party_form")

            return {'success': True, 'message': '材料上传完成，已进入完善案件信息'}

        except Exception:

            logger.warning("点击下一步后未进入完善案件信息页面")

            self._save_state(page, "party_form_wait_failed")

            return {'success': False, 'message': '材料上传后未能进入完善案件信息页面', 'next': next_result}

    def fill_party_form(self, page: Page, case_data: dict = None):

        """完善案件信息：标的金额、原告、被告、第三人、代理人。每类当事人填完保存后再继续。"""

        logger.info("填写当事人信息...")

        if not case_data:

            case_data = getattr(self, '_case_data', {}) or {}

        # Check if we're on the right page

        page_text = page.evaluate("() => document.body.innerText")

        if '完善案件信息' not in page_text:

            logger.warning(f"fill_party_form: 不在完善案件信息页面")

            if '选择立案案由' in page_text or '立案案由' in page_text:

                logger.info("尝试点击下一步进入完善案件信息")

                self._click_page_bottom_next(page)

                self._wait(2)

                page_text = page.evaluate("() => document.body.innerText")

                if '完善案件信息' not in page_text:

                    return {'ok': False, 'err': '无法进入完善案件信息页面'}

        # 0) 标的金额

        amount = case_data.get("claim_amount", case_data.get("amount", 0))

        try:

            self._fill_party_card_fields(page, {"标的金额(元)": str(amount)})

            logger.info(f"填写标的金额: {amount}")

        except Exception as e1:

            logger.warning(f"填标的金额失败: {e1}")

        self._wait(0.5)

        parties = case_data.get("parties", [])

        plaintiffs = [p for p in parties if p.get("party_type") == "原告"]

        defendants = [p for p in parties if p.get("party_type") == "被告"]

        thirds = [p for p in parties if p.get("party_type") == "第三人"]

        agents = [p for p in parties if p.get("party_type") == "代理人"]

        # 1) 原告：默认已有一张空白卡片，先编辑；后续根据 litigant_type 添加自然人或法人

        logger.info(f"当事人数量 - 原告: {len(plaintiffs)}, 被告: {len(defendants)}, 代理人: {len(agents)}")

        if plaintiffs:

            for idx, plaintiff in enumerate(plaintiffs):

                try:

                    litigant_type = plaintiff.get("litigant_type", "自然人")

                    add_btn = "添加法人" if litigant_type == "法人" else "添加自然人"

                    # Always use add button (like agent) to ensure save button appears

                    res = self._js_click_section_button(page, "原告信息", add_btn)

                    if not res.get('ok'):

                        # Fallback to edit if add fails

                        res = self._js_click_section_button(page, "原告信息", "编辑")

                    logger.info(f"打开原告卡片 #{idx+1} ({litigant_type}): {res}")

                    self._wait(3)

                    try:

                        page.wait_for_selector("uni-forms-item input:visible, .uni-forms-item input:visible, .fd-com-form-item input:visible", timeout=8000)

                        page.wait_for_timeout(500)

                    except Exception:

                        logger.warning(f"原告 #{idx+1} 卡片表单 input 未在 8s 内出现")

                    self._fill_party_current_card(page, plaintiff, role="原告")

                    save_res = self._click_card_save(page, party={**plaintiff, "__role": "原告"})

                    logger.info(f"保存原告 #{idx+1}: {save_res}")
                    # Verify save actually worked
                    if not save_res.get('ok'):
                        logger.warning(f"原告 #{idx+1} save failed, retrying with direct-vue-data...")
                        page.wait_for_timeout(1000)
                        # Force direct save by manipulating Vue data directly
                        force_save = page.evaluate("""() => {
                            function tagOf(v){ return v && v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name); }
                            function findAll(v, names, out){ out=out||[]; if(!v) return out; const t=tagOf(v); if(t&&names.includes(t)) out.push(v); for(const c of v.$children||[]) findAll(c,names,out); return out; }
                            const rootEl = document.querySelector('uni-app');
                            if (!rootEl || !rootEl.__vue__) return {err: 'no root vue'};
                            const comps = findAll(rootEl.__vue__, ['ryxx','Ryxx','sscyr','fd-sscyr']);
                            if (!comps.length) return {err: 'no ryxx'};
                            const ryxx = comps[0];
                            // Read from DOM inputs
                            function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }
                            const party = {};
                            const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea')).filter(isVisible);
                            for (const inp of inputs) {
                                const val = inp.value;
                                if (!val) continue;
                                const ph = inp.placeholder || '';
                                const parent = inp.closest('uni-forms-item, .uni-forms-item, [class*="form-item"]');
                                const label = parent ? (parent.querySelector('.uni-forms-item__label, .uni-forms-item__title, [class*="label"]') || {}).innerText || '' : '';
                                if (ph.includes('姓名') || label.includes('姓名')) party.name = val;
                                else if (ph.includes('证件') || label.includes('证件')) party.certNo = val;
                                else if (ph.includes('电话') || label.includes('电话')) party.phone = val;
                                else if (ph.includes('住所') || label.includes('住所')) party.address = val;
                                else if (label.includes('性别')) party.gender = val;
                                else if (label.includes('民族')) party.nation = val;
                                else if (label.includes('工作单位')) party.workUnit = val;
                                else if (label.includes('职务')) party.position = val;
                            }
                            if (!party.name) return {err: 'no name found in DOM', inputs: inputs.length};
                            // Add to ygList
                            if (!ryxx.ygList) ryxx.ygList = [];
                            if (ryxx.$data && !ryxx.$data.ygList) ryxx.$data.ygList = [];
                            const exists = ryxx.ygList.some(p => (p.name || p.xm) === party.name);
                            if (!exists) {
                                ryxx.ygList.push({...party});
                                if (ryxx.$data.ygList) ryxx.$data.ygList.push({...party});
                            }
                            // Close form
                            if (ryxx.showForm) { ryxx.showForm.yg = false; ryxx.showForm.bg = false; ryxx.showForm.dsr = false; ryxx.showForm.dlr = false; }
                            if (ryxx.formEdit !== undefined) ryxx.formEdit = false;
                            if (ryxx.$forceUpdate) ryxx.$forceUpdate();
                            return {ok: true, partyName: party.name, listLength: ryxx.ygList.length};
                        }""")
                        logger.info(f"Force direct save for 原告: {force_save}")

                    self._wait(2)

                except Exception as e:

                    logger.warning(f"原告 #{idx+1} 处理失败: {e}")

        else:

            logger.warning("案件无原告信息，跳过")

        # 2) 被告：全部添加并保存，根据 litigant_type 选择按钮

        if defendants:

            for idx, defendant in enumerate(defendants):

                try:

                    # 先确保原告表单已关闭

                    close_res = page.evaluate("""() => {

                        function find(v, tagName) {

                            if (!v) return null;

                            const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                            if (tag === tagName) return v;

                            for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }

                            return null;

                        }

                        const root = document.querySelector('uni-app').__vue__;

                        const ryxx = find(root, 'ryxx');

                        if (!ryxx) return {err: 'no ryxx'};

                        if (ryxx.showForm && typeof ryxx.showForm === 'object') {

                            Object.keys(ryxx.showForm).forEach(k => ryxx.showForm[k] = false);

                        }

                        if (ryxx.formEdit !== undefined) ryxx.formEdit = false;

                        ryxx.$forceUpdate && ryxx.$forceUpdate();

                        return {ok: true};

                    }""")

                    logger.info(f"关闭原告表单: {close_res}")

                    self._wait(1)

                    litigant_type = defendant.get("litigant_type", "自然人")

                    add_btn = "添加法人" if litigant_type == "法人" else "添加自然人"

                    res = self._js_click_section_button(page, "被告信息", add_btn)

                    logger.info(f"打开被告卡片 #{idx+1} ({litigant_type}): {res}")

                    self._wait(3)

                    # 等待被告卡片表单完全渲染

                    try:

                        page.wait_for_selector("uni-forms-item input:visible, .uni-forms-item input:visible, .fd-com-form-item input:visible", timeout=8000)

                        page.wait_for_timeout(500)

                    except Exception:

                        logger.warning(f"被告 #{idx+1} 卡片表单 input 未在 8s 内出现")

                    self._fill_party_current_card(page, defendant, role="被告")

                    save_res = self._click_card_save(page, party={**defendant, "__role": "被告"})

                    logger.info(f"保存被告 #{idx+1}: {save_res}")

                    self._wait(2)

                    # Verify defendant was actually saved - check Vue bgList data

                    verify = page.evaluate(r"""(defendantName) => {

                        // First check Vue bgList

                        function tagOf(v){ return v && v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name); }

                        function findAll(v, names, out){ out=out||[]; if(!v) return out; const t=tagOf(v); if(t&&names.includes(t)) out.push(v); for(const c of v.$children||[]) findAll(c,names,out); return out; }

                        const rootEl = document.querySelector('uni-app');

                        if (rootEl && rootEl.__vue__) {

                            const comps = findAll(rootEl.__vue__, ['ryxx','Ryxx','sscyr','fd-sscyr']);

                            if (comps.length) {

                                const ryxx = comps[0];

                                const bgList = ryxx.bgList || (ryxx.$data && ryxx.$data.bgList) || [];

                                const inBgList = bgList.some(p => {

                                    const name = p.name || p.xm || '';

                                    return name === defendantName || name.includes(defendantName);

                                });

                                if (inBgList) {

                                    return {has_defendant: true, method: 'vue-bgList', bgListLength: bgList.length};

                                }

                            }

                        }

                        // Fallback: check DOM

                        const sections = document.querySelectorAll('uni-section, .uni-section, section');

                        let defendantSection = null;

                        for (const s of sections) {

                            const t = (s.innerText || '').replace(/\s+/g, ' ').trim();

                            if (t.includes('被告信息')) {

                                defendantSection = s;

                                break;

                            }

                        }

                        if (!defendantSection) {

                            const text = document.body.innerText;

                            return {

                                has_defendant: text.includes(defendantName),

                                method: 'text-search',

                                page_text: text.substring(0, 500)

                            };

                        }

                        const cards = defendantSection.querySelectorAll('.fd-sscyr-card, [class*="card"], uni-view');

                        let found = false;

                        for (const card of cards) {

                            const t = (card.innerText || '');

                            if (t.includes(defendantName)) {

                                found = true;

                                break;

                            }

                        }

                        return {

                            has_defendant: found,

                            method: 'card-search',

                            section_text: (defendantSection.innerText || '').substring(0, 500)

                        };

                    }""", defendant.get("name", ""))

                    logger.info(f"被告保存验证: {verify}")

                    if not verify.get('has_defendant'):

                        logger.warning(f"被告 #{idx+1} 保存后未找到卡片，尝试重新保存")

                        save_res = self._click_card_save(page)

                        logger.info(f"重新保存被告 #{idx+1}: {save_res}")

                        self._wait(2)

                except Exception as e:

                    logger.warning(f"被告 #{idx+1} 处理失败: {e}")

        else:

            logger.warning("案件无被告信息，跳过")

        # 3) 第三人：有则添加保存，无则取消空白卡片，根据 litigant_type 选择按钮

        if thirds:

            for idx, third_party in enumerate(thirds):

                try:

                    litigant_type = third_party.get("litigant_type", "自然人")

                    add_btn = "添加法人" if litigant_type == "法人" else "添加自然人"

                    res = self._js_click_section_button(page, "第三人信息", add_btn)

                    logger.info(f"打开第三人卡片 #{idx+1} ({litigant_type}): {res}")

                    self._wait(3)

                    try:

                        page.wait_for_selector("uni-forms-item input:visible, .uni-forms-item input:visible, .fd-com-form-item input:visible", timeout=8000)

                        page.wait_for_timeout(500)

                    except Exception:

                        logger.warning(f"第三人 #{idx+1} 卡片表单 input 未在 8s 内出现")

                    self._fill_party_current_card(page, third_party, role="第三人")

                    save_res = self._click_card_save(page, party={**third_party, "__role": "第三人"})

                    logger.info(f"保存第三人 #{idx+1}: {save_res}")

                    self._wait(2)

                except Exception as e:

                    logger.warning(f"第三人 #{idx+1} 处理失败: {e}")

        else:

            self._cancel_empty_section(page, "第三人信息")

        # 4) 代理人：必填。先同步 store，再编辑/添加代理人卡片

        if not agents:

            first_plaintiff_name = (plaintiffs[0].get("name") if plaintiffs else "")

            agents = [{

                "name": "测试代理人",

                "cert_no": "110101199003033456",

                "phone": "13600000003",

                "agent_type": "执业律师",

                "license_no": "11101202410123456",

                "work_unit": "测试律师事务所",

                "represented_party": first_plaintiff_name,

            }]

            logger.info("使用默认代理人信息")

        # Ensure agents is a list of dicts

        valid_agents = []

        for a in agents:

            if isinstance(a, dict):

                valid_agents.append(a)

            elif isinstance(a, str):

                # Convert string to dict

                valid_agents.append({

                    "name": a,

                    "cert_no": "110101199003033456",

                    "phone": "13600000003",

                    "agent_type": "执业律师",

                    "license_no": "11101202410123456",

                    "work_unit": "测试律师事务所",

                    "represented_party": plaintiffs[0].get("name") if plaintiffs else "",

                })

        agents = valid_agents

        # 使用第一个原告作为默认被代理人

        default_represented = plaintiffs[0].get("name") if plaintiffs else ""

        # First delete all existing agents to avoid validation errors

        try:

            vue_delete_res = self._delete_existing_agents_vue(page)

            logger.info(f"删除现有代理人(Vue/API): {vue_delete_res}")

            agent_section = None

            if not (vue_delete_res.get('ok') and vue_delete_res.get('remaining', 0) == 0):

                agent_section = page.locator('text=代理人信息').first

            if agent_section is not None and agent_section.count() > 0:

                agent_section.scroll_into_view_if_needed(timeout=3000)

                page.wait_for_timeout(1000)

                # Find and click all delete buttons in agent section

                for _ in range(5):  # Max 5 agents to delete

                    delete_btns = page.locator('text=删除').all()

                    delete_clicked = False

                    for btn in delete_btns:

                        try:

                            btn_box = btn.bounding_box()

                            section_box = agent_section.bounding_box()

                            if btn_box and section_box:

                                dist = abs(btn_box['y'] - section_box['y'])

                                if dist < 500:

                                    btn.click(timeout=3000)

                                    page.wait_for_timeout(1500)

                                    # Confirm

                                    try:

                                        dialog_result = self._handle_delete_confirm_dialog(page)

                                        if dialog_result.get('ok'):

                                            delete_clicked = True

                                            logger.info(f"删除现有代理人: {dialog_result}")

                                            break

                                        else:

                                            # Fallback to old method

                                            confirm = page.locator('text=确定').first

                                            if confirm.count() > 0:

                                                confirm.click(timeout=2000)

                                                page.wait_for_timeout(1000)

                                                delete_clicked = True

                                                logger.info("删除现有代理人 (fallback)")

                                                break

                                    except:

                                        pass

                        except:

                            continue

                    if not delete_clicked:

                        break

        except Exception as e:

            logger.info(f"删除现有代理人失败: {e}")

        # Wait for page to stabilize after deletions

        page.wait_for_timeout(2000)

        # Now add new agents

        for idx, agent in enumerate(agents):

            try:

                logger.info(f"添加新代理人 #{idx + 1}")

                # Click add lawyer button

                add_result = self._js_click_section_button(page, "代理人信息", "添加律师")

                if not add_result.get('ok'):

                    add_result = self._js_click_section_button(page, "代理人信息", "添加法律服务工作者")

                if not add_result.get('ok'):

                    add_result = self._js_click_section_button(page, "代理人信息", "引入代理人")

                logger.info(f"打开添加代理人 #{idx + 1}: {add_result}")

                if add_result.get('ok'):

                    self._wait(2)

                    # Ensure editable

                    ensure_res = self._ensure_party_card_editable(page, "代理人信息")

                    logger.info(f"确保代理人卡片可编辑: {ensure_res}")

                    # Fill agent form - ensure agent is dict

                    if not isinstance(agent, dict):

                        agent = {

                            "name": str(agent) if agent else "测试代理人",

                            "cert_no": "110101199003033456",

                            "phone": "13600000003",

                            "agent_type": "执业律师",

                            "license_no": "11101202410123456",

                            "work_unit": "测试律师事务所",

                            "represented_party": plaintiffs[0].get("name") if plaintiffs else "",

                        }

                    fill_result = self._fill_party_current_card(page, agent, role="代理人")
                    logger.info(f"填写代理人 #{idx + 1}: {fill_result}")

                    # Set represented party (被代理人) - critical field that was previously skipped
                    represented = agent.get("represented_party", "")
                    if represented:
                        try:
                            rep_result = self._set_agent_represented(page, represented)
                            logger.info(f"设置被代理人 #{idx + 1}: {rep_result}")
                        except Exception as e:
                            logger.warning(f"设置被代理人失败 #{idx + 1}: {e}")

                    # Save
                    save_result = self._click_card_save(page, party={**agent, "__role": "代理人"})
                    logger.info(f"保存代理人 #{idx + 1}: {save_result}")

                    self._wait(2)

            except Exception as e:

                logger.warning(f"代理人 #{idx + 1} 处理失败: {e}")

        # 5) 标的额# 5) 全部保存后点击页面底部下一步

        # Use Vue injection to force close all forms

        close_res = page.evaluate("""() => {

            function find(v, tagName) {

                if (!v) return null;

                const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                if (tag === tagName) return v;

                for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }

                return null;

            }

            const root = document.querySelector('uni-app').__vue__;

            const ryxx = find(root, 'ryxx');

            if (!ryxx) return {err: 'no ryxx'};

            // Close all forms

            if (ryxx.showForm && typeof ryxx.showForm === 'object') {

                Object.keys(ryxx.showForm).forEach(k => ryxx.showForm[k] = false);

            }

            if (ryxx.formEdit !== undefined) ryxx.formEdit = false;

            if (ryxx.editIndex !== undefined) ryxx.editIndex = -1;

            if (ryxx.currentEditIndex !== undefined) ryxx.currentEditIndex = -1;

            ryxx.$forceUpdate && ryxx.$forceUpdate();

            return {ok: true, showForm: ryxx.showForm, formEdit: ryxx.formEdit};

        }""")

        logger.info(f"Vue 强制关闭表单: {close_res}")

        page.wait_for_timeout(1000)

        # 优先使用 Vue nextStep，失败时尝试点击按钮

        next_result = self._vue_click_next(page)

        if not next_result.get('ok'):

            logger.warning(f"Vue nextStep 失败，尝试点击按钮: {next_result}")

            self._click_page_bottom_next(page)

    def _delete_existing_agents_vue(self, page: Page) -> dict:

        """调用页面自身的 delRyxx 删除所有既有代理人，确保服务端草稿同步删除。"""

        try:

            return page.evaluate(r"""async () => {

                function find(v, tagName) {

                    if (!v) return null;

                    const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                    if (tag === tagName) return v;

                    for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }

                    return null;

                }

                function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

                const root = document.querySelector('uni-app') && document.querySelector('uni-app').__vue__;

                const ryxx = find(root, 'ryxx');

                if (!ryxx) return {err: 'no ryxx component'};

                const items = Array.from(ryxx.dlrs || []);

                if (!items.length) return {ok: true, attempted: 0, deleted: 0, remaining: 0};

                const errors = [];

                const oldShowModal = window.uni && uni.showModal;

                if (window.uni) {

                    uni.showModal = function(options) {

                        if (options && typeof options.success === 'function') {

                            setTimeout(() => options.success({confirm: true}), 0);

                        }

                    };

                }

                try {

                    for (const item of items) {

                        try {

                            ryxx.delRyxx(item, 'dlr');

                            await sleep(2600);  // delRyxx 在 toast 结束后才 init 刷新

                        } catch (e) {

                            errors.push(String(e && (e.message || e)));

                        }

                    }

                } finally {

                    if (window.uni && oldShowModal) uni.showModal = oldShowModal;

                }

                let stored = {};

                try { stored = JSON.parse(sessionStorage.getItem('layyInfo') || '{}'); } catch(e) {}

                const remaining = Array.isArray(stored.dlrs) ? stored.dlrs.length : ((ryxx.dlrs || []).length);

                return {ok: errors.length === 0 && remaining === 0, attempted: items.length, deleted: items.length - remaining, remaining, errors};

            }""")

        except Exception as e:

            return {'ok': False, 'err': str(e)}

    def _sync_party_store(self, page: Page) -> dict:

        """调用页面 Vue 当事人列表刷新方法，确保代理人被代理人选项可用"""

        return page.evaluate(r"""async () => {

            function find(v, tagName) {

                if (!v) return null;

                const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                if (tag === tagName) return v;

                for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }

                return null;

            }

            function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

            async function withTimeout(promise, ms) {

                const t = new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), ms));

                try { return await Promise.race([promise, t]); } catch(e) { return String(e.message || e); }

            }

            async function safeCall(vm, fn, args, timeoutMs) {

                try {

                    if (!vm || typeof vm[fn] !== 'function') return 'not-function';

                    const r = args != null ? vm[fn](args) : vm[fn]();

                    if (r && typeof r.then === 'function') return await withTimeout(r, timeoutMs || 3000);

                    return 'ok';

                } catch(e) { return String(e.message || e); }

            }

            function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

            const root = document.querySelector('uni-app').__vue__;

            const wsla = find(root, 'pagesWsla-common-wsla-index');

            const ryxx = find(root, 'ryxx');

            const results = {wsla: !!wsla, ryxx: !!ryxx};

            if (ryxx) {

                // ryxx.init() 会重置 showForm/formEdit，导致当前打开的代理人编辑表单被关闭。
                // 编辑期间只刷新当事人列表；没有表单打开时才允许完整 init。
                const editingForm = ryxx.formEdit === true || Object.values(ryxx.showForm || {}).some(Boolean);

                results.ryxxEditingForm = editingForm;

                results.ryxxGetDsrList = await safeCall(ryxx, 'getDsrList', null, 3000);

                await sleep(200);

                if (!editingForm) {

                    results.ryxxInit = await safeCall(ryxx, 'init', null, 3000);

                    await sleep(200);

                } else {

                    results.ryxxInit = 'skipped-editing-form';

                }

                results.ryxxDsrLen = ryxx.dsrList ? ryxx.dsrList.length : 0;

                results.ryxxSqrLen = ryxx.sqrList ? ryxx.sqrList.length : 0;

                results.ryxxBgrLen = ryxx.bgrList ? ryxx.bgrList.length : 0;

            }

            if (wsla) {

                results.wslaGetDsrList = await safeCall(wsla, 'getDsrList', null, 3000);

                results.wslaGetSqrList = await safeCall(wsla, 'getSqrList', null, 3000);

                results.wslaGetBgrList = await safeCall(wsla, 'getBgrList', null, 3000);

                results.wslaGetDsrAll = await safeCall(wsla, 'getDsrAll', null, 3000);

                await sleep(200);

                results.wslaDsrLen = wsla.dsrList ? wsla.dsrList.length : 0;

                results.wslaSqrLen = wsla.sqrList ? wsla.sqrList.length : 0;

                results.wslaBgrLen = wsla.bgrList ? wsla.bgrList.length : 0;

                if (ryxx && (!wsla.dsrList || wsla.dsrList.length === 0) && ryxx.dsrList) {

                    wsla.dsrList = ryxx.dsrList;

                    wsla.sqrList = ryxx.sqrList;

                    wsla.bgrList = ryxx.bgrList;

                    results.syncedFromRyxx = true;

                }

            }

            function scanCards() {

                const names = [];

                const cards = Array.from(document.querySelectorAll('uni-view, .fd-sscyr-info-item, .fd-sscyr-card, .fd-sscyr-list-item, [class*="sscyr"]')).filter(isVisible);

                for (const card of cards) {

                    const txt = (card.innerText || '').replace(/\s+/g, ' ').trim();

                    const m = txt.match(/姓名[：:]\s*([一-龥]{2,6})/);

                    if (m && !names.includes(m[1])) names.push(m[1]);

                }

                return names;

            }

            results.domPartyNames = scanCards();

            await sleep(300);

            return results;

        }""")

    def _set_agent_represented(self, page: Page, represented_party: str) -> dict:

        """在代理人编辑表单内勾选指定姓名的被代理人。优先在 DOM 中点击；若不行则注入 Vue 组件。"""

        # 先同步 store，确保被代理人列表已加载

        try:

            sync_res = self._sync_party_store(page)

        except Exception as e:

            sync_res = {'err': str(e)}

        dom_names = sync_res.get('domPartyNames', []) if isinstance(sync_res, dict) else []

        # Try Playwright approach first: click the checkbox INSIDE the open edit form.
        # 注意：不能使用全局 text= 点击——页面上已保存的当事人卡片也显示相同姓名，
        # 误点卡片会触发 doEdit 关闭当前编辑表单。

        target_name = represented_party  # Capture parameter in local scope

        try:

            checkbox_sels = [

                f'uni-forms-item:has-text("被代理人") .uni-checkbox-wrapper:has-text("{target_name}")',

                f'uni-forms-item:has-text("被代理人") uni-checkbox:has-text("{target_name}")',

                f'uni-forms-item:has-text("被代理人") uni-label:has-text("{target_name}")',

                f'uni-forms-item:has-text("被代理人") [class*="checkbox"]:has-text("{target_name}")',

            ]

            for sel in checkbox_sels:

                try:

                    cb = page.locator(sel).first

                    if cb.count() > 0 and cb.is_visible(timeout=1500):

                        cb.click(timeout=3000)

                        page.wait_for_timeout(500)

                        return {'ok': True, 'method': 'form-checkbox-click', 'value': target_name, 'selector': sel}

                except Exception:

                    continue

        except Exception as e:

            logger.debug(f"Playwright 选择被代理人失败: {e}")

        # Fallback to JS DOM approach

        return page.evaluate(r"""async (args) => {

            const targetName = args.represented_party;

            const syncNames = args.sync_names || [];

            function isVisible(el) {

                if (!el) return false;

                const r = el.getBoundingClientRect();

                return r.width > 0 && r.height > 0 && r.top >= -r.height && r.left >= -r.width;

            }

            function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

            function clickEl(el) {

                if (!el) return;

                el.focus && el.focus();

                el.click();

                const inp = el.querySelector ? el.querySelector('input[type="checkbox"], input[type="radio"]') : null;

                if (inp) {

                    inp.checked = true;

                    inp.dispatchEvent(new Event('change', {bubbles: true}));

                }

            }

            // 0) 优先：在包含复选框的 被代理人 表单项内直接勾选目标姓名

            {

                const items0 = Array.from(document.querySelectorAll('uni-forms-item, .uni-forms-item, .fd-com-form-item')).filter(isVisible);

                for (const it of items0) {

                    const lb = it.querySelector('.uni-forms-item__label, .uni-forms-item__title, .fd-form-label, .label, [class*="label"]');

                    if (!lb || !(lb.innerText || '').includes('被代理人')) continue;

                    if (!it.querySelector('.uni-checkbox-wrapper, uni-checkbox, input[type="checkbox"], [class*="checkbox"]')) continue;

                    const opts = it.querySelectorAll('.uni-checkbox-wrapper, uni-checkbox, uni-label, label, [class*="checkbox"]');

                    for (const op of opts) {

                        if (!isVisible(op)) continue;

                        const t = (op.innerText || '').replace(/\s+/g, ' ').trim();

                        if (t === targetName || (t.includes(targetName) && t.length <= targetName.length + 4)) {

                            clickEl(op);

                            return {ok: true, method: 'scoped-checkbox', text: t};

                        }

                    }

                    return {err: 'bdlr option not found in form', options: Array.from(opts).map(o => (o.innerText || '').trim()).slice(0, 10)};

                }

            }

            // 1) 展开/点击 被代理人 表单项，观察是否出现选项层

            const formItems = Array.from(document.querySelectorAll('uni-forms-item, .uni-forms-item, .fd-com-form-item')).filter(isVisible);

            let bdlrItem = null;

            for (const item of formItems) {

                const label = item.querySelector('.uni-forms-item__label, .uni-forms-item__title, .fd-form-label, .label, [class*="label"]');

                if (label && (label.innerText || '').includes('被代理人')) {

                    bdlrItem = item;

                    break;

                }

            }

            if (bdlrItem) {

                const content = bdlrItem.querySelector('.uni-forms-item__content') || bdlrItem;

                content.click();

                await sleep(600);

                // 有时候选项以弹层/下拉形式在 body 底部

                const bodyText = document.body.innerText || '';

                if (!bodyText.includes(targetName)) {

                    const label = bdlrItem.querySelector('.uni-forms-item__label, .uni-forms-item__title, .fd-form-label, .label, [class*="label"]');

                    if (label) label.click();

                    await sleep(600);

                }

            }

            // 2) 在可见元素里找“自身文本”精确等于目标姓名的复选项（避免误点包含全文的大容器）

            const all = Array.from(document.querySelectorAll('uni-label, label, .checklist-box, .uni-checkbox, .uni-checkbox-wrapper, .uni-data-checklist__item, [class*="checkbox"], [class*="checklist"], uni-checkbox, [class*="bdlr"], [class*="represented"]')).filter(isVisible);

            let boxCount = 0;

            const seen = new Set();

            for (const el of all) {

                if (seen.has(el)) continue;

                seen.add(el);

                let own = '';

                for (const n of el.childNodes) { if (n.nodeType === 3) own += n.textContent; }

                let txt = (own || el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();

                if (txt === targetName || (txt.includes(targetName) && txt.length <= targetName.length + 4)) {

                    clickEl(el);

                    return {ok: true, method: 'dom-text-exact', text: txt, boxCount: all.length};

                }

                if (txt && (txt.includes('被代理人') || txt.includes('选择被代理人'))) boxCount++;

            }

            // 3) 在弹层列表里精确匹配姓名(有些选项只在弹层打开后渲染)

            const popupItems = Array.from(document.querySelectorAll('.uni-popup__wrapper .uni-list-item, .uni-popup__wrapper uni-view, .uni-popup__wrapper label, .uni-select__item, .uni-picker-item')).filter(isVisible);

            for (const el of popupItems) {

                const txt = (el.innerText || '').replace(/\s+/g, ' ').trim();

                if (txt === targetName || txt.includes(targetName)) {

                    clickEl(el);

                    return {ok: true, method: 'popup-item', text: txt, boxCount: popupItems.length};

                }

            }

            // 4) Vue 注入：扫描组件树，找包含 bdlrList / agentForm 的组件

            function scanVue(v, depth) {

                if (!v || depth > 20) return [];

                let out = [];

                const keys = Object.keys(v);

                const hasBdlr = keys.some(k => /bdlr/i.test(k));

                const hasAgentForm = keys.some(k => /agentForm/i.test(k));

                if (hasBdlr || hasAgentForm) {

                    const tag = v.$options && (v.$options.name || v.$options.__name || v.$options._componentTag || 'unknown');

                    out.push({depth, tag, keys: keys.filter(k => /bdlr|agentForm|dsr|sqr|bgr/i.test(k)), vm: v});

                }

                for (const c of v.$children || []) out = out.concat(scanVue(c, depth+1));

                return out;

            }

            const root = document.querySelector('uni-app').__vue__;

            if (!root) return {err: 'no vue root', boxCount};

            const candidates = scanVue(root, 0);

            if (!candidates.length) return {err: 'no agent vue component', targetName, boxCount};

            const agent = candidates.sort((a,b) => a.depth - b.depth)[0].vm;

            // 5) 匹配姓名：优先使用 syncNames，否则从 DOM/Vue 数据收集

            function collectPartyNames(v) {

                const names = new Set();

                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);

                let node;

                while (node = walker.nextNode()) {

                    const t = (node.textContent || '').trim();

                    if (t && t !== targetName && /[一-龥]{2,6}/.test(t)) names.add(t);

                }

                function scanData(obj, seen) {

                    if (!obj || seen.has(obj)) return;

                    seen.add(obj);

                    if (Array.isArray(obj)) {

                        for (const item of obj) {

                            if (item && (item.name || item.xm || item.dsrName)) {

                                const n = item.name || item.xm || item.dsrName;

                                if (n) names.add(n);

                            } else scanData(item, seen);

                        }

                    } else if (typeof obj === 'object') {

                        for (const k of Object.keys(obj)) scanData(obj[k], seen);

                    }

                }

                scanData(v.$data || v, new Set());

                if (v.$store && v.$store.state) scanData(v.$store.state, new Set());

                return Array.from(names);

            }

            const allNames = collectPartyNames(root);

            let matchedName = targetName;

            for (const n of syncNames) {

                if (n === targetName || n.includes(targetName) || targetName.includes(n)) { matchedName = n; break; }

            }

            if (matchedName === targetName) {

                const candidates2 = allNames.filter(n => n === targetName || n.includes(targetName) || targetName.includes(n));

                if (candidates2.length) matchedName = candidates2[0];

            }

            // 6) 构造被代理人对象并写入多个可能位置

            const candidate = { name: matchedName, xm: matchedName, dsrName: matchedName, id: matchedName };

            function setAgent(vm) {

                if (!vm) return;

                let changed = false;

                if (vm.agentForm) {

                    vm.agentForm.bdlrList = [candidate];

                    vm.agentForm.bdlr = [matchedName];

                    if (vm.agentForm.bdlrId !== undefined) vm.agentForm.bdlrId = [matchedName];

                    changed = true;

                }

                if (vm.bdlrList !== undefined) { vm.bdlrList = [candidate]; changed = true; }

                if (vm.bdlr !== undefined) { vm.bdlr = [matchedName]; changed = true; }

                if (vm.bdlrId !== undefined) { vm.bdlrId = [matchedName]; changed = true; }

                if (changed) vm.$forceUpdate && vm.$forceUpdate();

            }

            setAgent(agent);

            // 同时更新 wsla / ryxx 上的 agentForm

            function find(v, tagName) {

                if (!v) return null;

                const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                if (tag === tagName) return v;

                for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }

                return null;

            }

            const wsla = find(root, 'pagesWsla-common-wsla-index');

            const ryxx = find(root, 'ryxx');

            setAgent(wsla);

            setAgent(ryxx);

            return {ok: true, method: 'vue-inject', name: matchedName, component: agent.$options && (agent.$options.name || agent.$options.__name), boxCount, allNames: allNames.slice(0, 10)};

        }""", {"represented_party": represented_party, "sync_names": dom_names})

    def _fill_party_current_card(self, page: Page, party: dict, role: str = "原告"):

        """根据当前卡片字段填写当事人信息"""

        # Ensure party is dict

        if not isinstance(party, dict):

            party = {

                "name": str(party) if party else "测试人员",

                "cert_no": "110101199003033456",

                "phone": "13600000003",

            }

        values = {}

        # 通用字段

        if party.get("name"):

            values["姓名"] = party["name"]

        cert_no = party.get("cert_no") or party.get("idcard") or ""

        if cert_no:

            values["证件号码"] = cert_no

        if party.get("phone"):

            values["联系电话"] = party["phone"]

        if party.get("address"):

            values["住所地(户籍所在地)"] = party["address"]

            values["经常居住地"] = party["address"]

        if role == "代理人":

            # 实际页面字段：被代理人、代理人类型、姓名、代理人证件类型、代理人证件号码、单位、联系电话

            values["被代理人"] = party.get("represented_party", "") or party.get("principal", "")

            values["代理人类型"] = party.get("agent_type", "执业律师") or "执业律师"

            values["代理人证件类型"] = party.get("cert_type", "居民身份证") or "居民身份证"

            values["代理人证件号码"] = cert_no

            values["单位"] = party.get("work_unit", "") or "律师事务所"

            # 代理人不需要通用当事人的 工作单位/职务/性别/国别/民族/住所地 等字段

            for k in ["工作单位", "职务", "性别", "国别或地区", "民族", "住所地(户籍所在地)", "经常居住地"]:

                values.pop(k, None)

        else:

            # Check if this is a legal person (法人)

            litigant_type = party.get("litigant_type", "自然人")

            if litigant_type == "法人":

                # 法人特定字段

                values["名称"] = party.get("name", "")

                values["统一社会信用代码"] = party.get("cert_no", "")

                values["法定代表人/负责人"] = party.get("legal_person", "") or party.get("name", "")

                values["法定代表人手机号码"] = party.get("phone", "")

                values["法定代表人证件号码"] = party.get("legal_person_id", "") or party.get("cert_no", "")

                values["住所地(主要办事机构所在地)"] = party.get("address", "")

                values["注册地/登记地"] = party.get("registered_address", "") or party.get("address", "")

                # 类型：使用 litigant_type 的值(法人/非法人组织)，而不是 org_type

                values["类型"] = party.get("litigant_type", "法人") or "法人"

                # 证照类型：经真实网站探测（tests/probe_cert_types.py），法人表单的

                # 「证照类型」下拉真实选项为「统一社会信用代码证」；此前误用的「法人」

                # 实为「类型」下拉的选项，选不中会导致"证照类型不能为空"校验拦截。

                values["证照类型"] = "统一社会信用代码证"

                # 移除备用值，避免混淆

                values.pop("证照类型(统一社会信用代码)", None)

                # Remove natural person specific fields

                for k in ["姓名", "证件号码", "联系电话", "住所地(户籍所在地)", "经常居住地", "性别", "民族"]:

                    values.pop(k, None)

            else:

                # 自然人特定字段

                values["证件类型"] = party.get("cert_type", "居民身份证") or "居民身份证"

                values["性别"] = party.get("gender", "男") or "男"

                values["民族"] = party.get("nation", "汉族") or "汉族"

            # 自然人/法人共同字段

            values["工作单位"] = party.get("work_unit", "无") or "无"

            # 职务：使用传入的 position，或从 job 取；空值或裸"其他"统一映射为完整选项。
            # 真实页面职务选项中没有独立的"其他"，裸"其他"保存后 zyMc 为空，预览不显示职务。

            position = party.get("position", "") or party.get("job", "") or ""

            if not position or position == "其他":

                position = "其他办事人员和有关人员"

            values["职务"] = position

            values["国别或地区"] = party.get("country", "中国") or "中国"

        # Wait for card form to fully render: wait for any visible input

        try:

            page.wait_for_selector("uni-forms-item input:visible, .uni-forms-item input:visible, .fd-com-form-item input:visible", timeout=8000)

            page.wait_for_timeout(500)

        except Exception:

            logger.warning(f"{role} 卡片表单 input 未在 8s 内出现，仍尝试填写")

        logger.info(f"准备填写 {role} 字段: {values}")

        res = self._fill_party_card_fields(page, values, role=role)

        logger.info(f"{role} 填写结果: {res}")

        # 单独处理代理人执业证号

        if role == "代理人" and (party.get("license_no") or ""):

            lic_res = self._fill_agent_license_no(page, party["license_no"])

            logger.info(f"填写代理人执业证号: {lic_res}")

        # Ensure save button is visible by setting Vue form state

        try:

            ensure_result = page.evaluate("""() => {

                function findVueComponent(v, names) {

                    if (!v) return null;

                    const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                    if (tag && names.includes(tag)) return v;

                    for (const c of v.$children || []) { 

                        const r = findVueComponent(c, names); 

                        if (r) return r; 

                    }

                    return null;

                }

                const root = document.querySelector('uni-app').__vue__;

                if (!root) return {err: 'no root'};

                // Find ryxx component (party info component)

                const ryxx = findVueComponent(root, ['ryxx', 'Ryxx', 'sscyr', 'fd-sscyr']);

                if (!ryxx) return {err: 'no ryxx component'};

                // Set formEdit to true and showForm to show current role

                if ('formEdit' in ryxx) {

                    ryxx.formEdit = true;

                }

                if ('showForm' in ryxx) {

                    // Determine which form to show based on role

                    const roleMap = {'原告': 'yg', '被告': 'bg', '第三人': 'dsr', '代理人': 'dlr'};

                    const formKey = roleMap['""" + role + """'] || 'yg';

                    ryxx.showForm = {yg: false, bg: false, dsr: false, dlr: false, fyjg: false};

                    ryxx.showForm[formKey] = true;

                }

                // Force update

                if (ryxx.$forceUpdate) {

                    ryxx.$forceUpdate();

                }

                return {ok: true, formEdit: ryxx.formEdit, showForm: ryxx.showForm};

            }""")

            logger.debug(f"Ensure save button visible: {ensure_result}")

        except Exception as e:

            logger.debug(f"Ensure save button failed: {e}")

        # Final verification: ensure cert_type is "居民身份证" not "其他"

        # Wait a bit for any async rendering to complete

        page.wait_for_timeout(1000)

        if role in ("原告", "被告") and party.get("litigant_type", "自然人") == "自然人":

            try:

                cert_fix = page.evaluate(r"""() => {

                    function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

                    const items = Array.from(document.querySelectorAll('uni-forms-item, .uni-forms-item, .fd-com-form-item')).filter(isVisible);

                    for (const item of items) {

                        const label = item.querySelector('.uni-forms-item__label, .uni-forms-item__title, .fd-form-label, .label');

                        if (!label) continue;

                        const t = (label.innerText || '').replace(/\s+/g, ' ').trim();

                        if (t.includes('证件类型')) {

                            // Skip read-only card display rows (saved party cards also render this label)

                            const interactive = item.querySelector('.uni-data-tree-input, .uni-select, .uni-picker, .fd-select-area, [class*="select"], [class*="picker"], [class*="dropdown"], input, textarea');

                            if (!interactive || !isVisible(interactive)) continue;

                            // Try multiple ways to get the value

                            const valueSelectors = ['.uni-select', '.uni-input-input', '[class*="value"]', '[class*="text"]', 'input'];

                            for (const vs of valueSelectors) {

                                const valueEl = item.querySelector(vs);

                                if (valueEl) {

                                    const currentVal = (valueEl.innerText || valueEl.value || '').trim();

                                    if (currentVal) {

                                        if (currentVal === '其他') {

                                            return {err: 'cert_type is 其他', needsFix: true, label: t, foundValue: currentVal};

                                        }

                                        return {ok: true, value: currentVal};

                                    }

                                }

                            }

                        }

                    }

                    return {err: 'cert_type field not found'};

                }""")

                if cert_fix.get('needsFix'):

                    logger.warning(f"{role} cert_type is '其他', attempting Vue fix...")

                    # Re-select cert_type dropdown properly

                    logger.info(f"{role} re-selecting cert_type dropdown...")

                    page.wait_for_timeout(500)

                    # Close any open popups

                    page.keyboard.press("Escape")

                    page.evaluate("() => { document.body.click(); }")

                    page.wait_for_timeout(500)

                    # Re-select via the proven dropdown helpers (skip read-only card rows)

                    click_res = self._js_click_dropdown_trigger(page, '证件类型')

                    if click_res.get('ok'):

                        page.wait_for_timeout(1200)

                        select_res = self._js_select_dropdown_option(page, '居民身份证')

                        logger.info(f"cert_type re-select result: {select_res}")

                    else:

                        select_res = click_res

                        logger.warning(f"cert_type re-select trigger failed: {click_res}")

                    # Close popup after re-select

                    page.keyboard.press("Escape")

                    page.evaluate("() => { document.body.click(); }")

                    page.wait_for_timeout(500)

                    # Re-select completed

            except Exception as e:

                logger.debug(f"cert_type verification failed: {e}")

        # 自然人：补齐派生字段(出生日期/年龄/工作单位/职务显示名)并写入当前编辑表单，
        # 否则服务端草稿缺 csrq/nl/gzdw/zyMc，预览页对应栏目为空。

        if role != "代理人" and party.get("litigant_type", "自然人") == "自然人":

            try:

                derived = self._ensure_party_derived_fields(page, party, role)

                logger.info(f"{role} 派生字段补齐: {derived}")

            except Exception as e:

                logger.warning(f"{role} 派生字段补齐失败: {e}")

        return res

    def _ensure_party_derived_fields(self, page: Page, party: dict, role: str = "原告") -> dict:

        """把自然人派生字段写入当前打开的编辑表单(addSscyr.formData)。

        站点自身的 zjhm 输入监听只有在证件号发生真实输入变化时才派生 csrq/nl/xb；
        草稿回填或 JS 赋值后证件号未变化时不会触发，导致保存到服务端的当事人缺
        出生日期(csrq)、年龄(nl)。职务显示名(zyMc)依赖 codeList.zy 反查，若下拉
        选择异常也会为空。这里在保存前显式补齐。
        """

        cert_no = (party.get("cert_no") or party.get("idcard") or "")

        work_unit = party.get("work_unit", "") or "无"

        position = party.get("position", "") or party.get("job", "") or ""

        if not position or position == "其他":

            position = "其他办事人员和有关人员"

        return page.evaluate(r"""(args) => {

            const certNo = (args.certNo || '').trim();

            const workUnit = args.workUnit || '';

            const positionText = args.position || '';

            const rootEl = document.querySelector('uni-app');

            if (!rootEl || !rootEl.__vue__) return {err: 'no vue root'};

            function tagOf(v){ return v && v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name); }

            function findAll(v, out){ out = out || []; if (!v) return out; out.push(v); for (const c of v.$children || []) findAll(c, out); return out; }

            function isVisibleEl(el){ if (!el || !el.getBoundingClientRect) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

            const all = findAll(rootEl.__vue__);

            // 当前打开的编辑表单组件：tag 为 addSscyr，或 formData 含当事人字段；优先取可见实例

            const candidates = all.filter(v => {

                const fd = v.formData;

                if (!fd || typeof fd !== 'object') return false;

                const tag = tagOf(v) || '';

                return /addSscyr|sscyr/i.test(tag) || ('zjhm' in fd) || ('dsrlx' in fd && 'xm' in fd);

            });

            const visibleEditors = candidates.filter(v => isVisibleEl(v.$el));

            const editors = visibleEditors.length ? visibleEditors : candidates;

            if (!editors.length) {

                const fdTags = all.filter(v => v.formData && typeof v.formData === 'object').map(v => tagOf(v) || '?');

                return {err: 'no edit form', scanned: all.length, formDataComponents: fdTags.slice(0, 10)};

            }

            const comp = editors[0];

            const fd = comp.formData;

            const setF = (k, val) => {

                try { if (comp.$set) comp.$set(fd, k, val); else fd[k] = val; }

                catch(e) { try { fd[k] = val; } catch(e2){} }

            };

            const patched = {};

            const id = (fd.zjhm || certNo || '').trim();

            // 1) 出生日期/年龄/性别：18 位居民身份证派生

            if (/^\d{17}[\dXx]$/.test(id)) {

                if (!fd.csrq) {

                    const csrq = id.substring(6, 10) + '-' + id.substring(10, 12) + '-' + id.substring(12, 14);

                    setF('csrq', csrq); patched.csrq = csrq;

                }

                // 年龄必须为 1-3 位数字字符串；站点 watcher 可能把日期串覆盖进 nl，需要校正

                if (!/^\d{1,3}$/.test(String(fd.nl === undefined || fd.nl === null ? '' : fd.nl))) {

                    const birth = new Date(+id.substring(6, 10), +id.substring(10, 12) - 1, +id.substring(12, 14));

                    const now = new Date();

                    let age = now.getFullYear() - birth.getFullYear();

                    if (now.getMonth() < birth.getMonth() || (now.getMonth() === birth.getMonth() && now.getDate() < birth.getDate())) age--;

                    setF('nl', String(age)); patched.nl = String(age);

                }

                if (!fd.xb) {

                    const male = (+id.charAt(16)) % 2 === 1;

                    const xbText = male ? '男' : '女';

                    const xbList = (comp.codeList && comp.codeList.xb) || [];

                    const hit = xbList.find(o => (o.text || o.label || '') === xbText);

                    if (hit) { setF('xb', hit.value); patched.xb = hit.value; }

                    if (!fd.cxb) setF('cxb', xbText);

                }

            }

            // 2) 工作单位

            if ((fd.gzdw === undefined || fd.gzdw === null || fd.gzdw === '') && workUnit) {

                setF('gzdw', workUnit); patched.gzdw = workUnit;

            }

            // 3) 职务显示名：先按 codeList.zy 反查已有 zy 代码，失败则按目标文本定位代码

            if (!fd.zyMc) {

                const zyList = (comp.codeList && comp.codeList.zy) || [];

                let hit = fd.zy ? zyList.find(o => o.value === fd.zy && (o.text || o.label || '') !== '其他') : null;

                if (hit) {

                    setF('zyMc', hit.text || hit.label); patched.zyMc = hit.text || hit.label;

                } else {

                    hit = zyList.find(o => (o.text || o.label || '') === positionText);

                    if (hit) {

                        setF('zy', hit.value); setF('zyMc', hit.text || hit.label);

                        patched.zy = hit.value; patched.zyMc = hit.text || hit.label;

                    } else if (positionText) {

                        setF('zyMc', positionText); patched.zyMc = positionText;

                    }

                }

            }

            // 4) 同步到当前编辑对象镜像(addSscyr 的 ryxx prop 与 ryxx 组件的 ryxx)，
            //    防止保存序列化其他对象时丢字段

            const mirrors = [];

            if (comp.ryxx && typeof comp.ryxx === 'object') mirrors.push(comp.ryxx);

            try {

                function findTag(v, name){ if (!v) return null; const t = tagOf(v); if (t === name) return v; for (const c of v.$children || []) { const r = findTag(c, name); if (r) return r; } return null; }

                const ryxxComp = findTag(rootEl.__vue__, 'ryxx');

                if (ryxxComp && ryxxComp.ryxx && typeof ryxxComp.ryxx === 'object') mirrors.push(ryxxComp.ryxx);

            } catch(e) {}

            for (const m of mirrors) {

                for (const k of ['csrq', 'nl', 'gzdw', 'zyMc', 'zy', 'xb', 'cxb']) {

                    if ((m[k] === undefined || m[k] === null || m[k] === '') && fd[k] !== undefined && fd[k] !== '') {

                        try { m[k] = fd[k]; } catch(e){}

                    }

                }

            }

            if (comp.$forceUpdate) comp.$forceUpdate();

            return {ok: true, patched: patched, zjhm: id, mirrors: mirrors.length};

        }""", {"certNo": cert_no, "workUnit": work_unit, "position": position})

    def _fill_agent_license_no(self, page: Page, value: str):

        """代理人执业证号：尝试常见 label / placeholder / 输入框上下文"""

        return page.evaluate(r"""(value) => {

            function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

            function setNativeValue(el, v) {

                const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value') || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');

                if (descriptor && descriptor.set) descriptor.set.call(el, v); else el.value = v;

                el.dispatchEvent(new Event('input', {bubbles:true}));

                el.dispatchEvent(new Event('change', {bubbles:true}));

                el.dispatchEvent(new Event('blur', {bubbles:true}));

            }

            const items = Array.from(document.querySelectorAll('uni-forms-item, .uni-forms-item, .fd-com-form-item')).filter(isVisible);

            for (const item of items) {

                const label = item.querySelector('.uni-forms-item__label, .uni-forms-item__title, .fd-form-label, .label, [class*="label"]');

                const t = (label && (label.innerText || '')) || '';

                if (/执业证号|律师执业证号|执业证|证号/.test(t)) {

                    const inp = item.querySelector('input, textarea');

                    if (inp && !inp.readOnly && !inp.disabled) {

                        inp.focus(); inp.click(); setNativeValue(inp, value);

                        return {ok: true, method: 'label', label: t};

                    }

                }

            }

            const inputs = Array.from(document.querySelectorAll('input, textarea')).filter(isVisible);

            for (const inp of inputs) {

                const ph = (inp.placeholder || '').replace(/\s+/g, '');

                if (/执业证号|律师执业证号/.test(ph) && !inp.readOnly && !inp.disabled) {

                    inp.focus(); inp.click(); setNativeValue(inp, value);

                    return {ok: true, method: 'placeholder', placeholder: ph};

                }

            }

            let lastCandidate = null;

            for (const inp of inputs) {

                if (inp.readOnly || inp.disabled || inp.type === 'hidden') continue;

                if (!inp.value && !lastCandidate) lastCandidate = inp;

            }

            if (lastCandidate) { lastCandidate.focus(); lastCandidate.click(); setNativeValue(lastCandidate, value); return {ok: true, method: 'empty-input'}; }

            return {err: 'license input not found'};

        }""", value)

    def _debug_agent_form(self, page: Page, tag: str = "") -> dict:

        """调试：dump 代理人编辑表单的字段、按钮、输入框状态"""

        try:

            return page.evaluate(r"""(tag) => {

                function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

                const result = {tag: tag};

                // find agent section

                const all = Array.from(document.querySelectorAll('uni-section, .uni-section, section, uni-view, div, uni-section-header')).filter(isVisible);

                let section = null;

                for (const el of all) {

                    const t = (el.innerText || '').replace(/\s+/g, ' ').trim();

                    if (t.includes('代理人信息')) {

                        if (el.tagName === 'UNI-SECTION' || (el.className && el.className.includes('uni-section') && !el.className.includes('uni-section-header'))) { section = el; break; }

                        if (!section) section = el;

                    }

                }

                if (!section) return {err: 'agent section not found', tag};

                // collect form items

                const items = Array.from(section.querySelectorAll('uni-forms-item, .uni-forms-item, .fd-com-form-item')).filter(isVisible);

                result.items = items.map(item => {

                    const label = item.querySelector('.uni-forms-item__label, .uni-forms-item__title, .fd-form-label, .label, [class*="label"]');

                    const inp = item.querySelector('input, textarea');

                    return {

                        label: label ? (label.innerText || '').trim() : '',

                        hasInput: !!inp,

                        readOnly: inp ? inp.readOnly : null,

                        disabled: inp ? inp.disabled : null,

                        value: inp ? inp.value : null

                    };

                });

                // collect buttons in section

                const btns = Array.from(section.querySelectorAll('uni-button, button, [class*="btn"]')).filter(isVisible);

                result.buttons = btns.map(b => (b.innerText || '').replace(/\s+/g, ' ').trim());

                return result;

            }""", tag)

        except Exception as e:

            return {'err': str(e)}

    def _add_party_by_section(self, page: Page, section_title: str, party: dict, role: str = "原告", agent_type: str = "自然人"):

        """在指定区域点击添加按钮并填写"""

        btn_map = {

            "原告": "添加自然人",

            "被告": "添加自然人",

            "第三人": "添加自然人",

            "代理人": "添加律师",

        }

        btn_text = btn_map.get(role, "添加自然人")

        try:

            result = self._js_click_section_button(page, section_title, btn_text)

            if result.get('ok'):

                logger.info(f"点击 {section_title} {btn_text}")

            else:

                logger.warning(f"点击 {section_title} 添加按钮失败: {result}")

        except Exception as e:

            logger.warning(f"点击 {section_title} 添加按钮异常: {e}")

        self._wait(2)

        self._fill_party_dialog(page, party, role=role)

    def _fill_party_dialog(self, page: Page, party: dict, role: str = "原告"):

        """在当事人编辑/添加弹窗中填写完整字段。使用 _fill_party_current_card 的字段映射逻辑。"""

        # 使用现有的字段映射和填写逻辑

        self._fill_party_current_card(page, party, role=role)

        # 保存

        self._click_card_save(page)

    def _cancel_empty_section(self, page: Page, section_title: str):

        """如果某区域默认展开了空白编辑表单，尝试取消"""

        try:

            loc = page.locator("text=" + section_title).first

            if loc.count() and loc.is_visible():

                section = loc.locator("xpath=../../..")

                cancel = section.locator("text=取消").first

                if cancel.count() and cancel.is_visible():

                    cancel.click(timeout=3000)

                    logger.info(f"取消 {section_title} 空白表单")

                    self._wait(0.5)

        except Exception as e:

            logger.debug(f"取消 {section_title} 表单忽略: {e}")

    # ------------------------------------------------------------------

    # 通用 JS 辅助函数：在页面内根据可见文本/类名操作 DOM

    # ------------------------------------------------------------------

    def _js_click_text(self, page: Page, text: str, exact: bool = False, tag_filter: str = None, timeout: int = 5000) -> dict:

        """用 JS 点击页面上可见文本匹配的第一个元素"""

        script = """(args) => {

            const text = args.text, exact = args.exact, tagFilter = args.tagFilter;

            function isVisible(el) {

                const r = el.getBoundingClientRect();

                return r.width > 0 && r.height > 0 && r.top >= -r.height && r.left >= -r.width;

            }

            let selector = tagFilter || 'uni-view, uni-button, button, div, span, a';

            let all = document.querySelectorAll(selector);

            // 1) exact match

            for (const el of all) {

                if (!isVisible(el)) continue;

                const t = (el.innerText || '').trim();

                if (t === text) { el.click(); return {ok: true, text, exact: true, tag: el.tagName}; }

            }

            if (exact) return {err: 'not found exact', text};

            // 2) contains

            for (const el of all) {

                if (!isVisible(el)) continue;

                const t = (el.innerText || '').trim();

                if (t.includes(text)) { el.click(); return {ok: true, text, contains: true, tag: el.tagName}; }

            }

            // 3) fallback: any element with text node

            all = document.querySelectorAll('*');

            for (const el of all) {

                if (!isVisible(el)) continue;

                for (const node of el.childNodes) {

                    if (node.nodeType === 3 && (node.textContent || '').trim().includes(text)) {

                        el.click(); return {ok: true, text, fallback: true, tag: el.tagName};

                    }

                }

            }

            return {err: 'not found', text};

        }"""

        return page.evaluate(script, {"text": text, "exact": exact, "tagFilter": tag_filter})

    def _fill_party_card_fields(self, page: Page, values: dict, role: str = '原告', _is_retry: bool = False) -> dict:

        """Fill all visible fields in the currently opened party card using JS DOM + Python-side waits."""

        results = {}

        for label, value in values.items():

            if value is None or value == '' or str(value).strip() == '':

                results[label] = {'ok': True, 'skipped': 'empty'}

                continue

            str_val = str(value)

            try:

                item_info = page.evaluate(r"""(label) => {

                    function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

                    // Try multiple container patterns

                    const containers = [

                        'uni-forms-item', '.uni-forms-item', '.fd-com-form-item',

                        '.fd-form-item', '.form-item', '.uni-form-item',

                        '[class*="form-item"]', '[class*="formItem"]'

                    ];

                    let readonlyMatch = null;

                    for (const sel of containers) {

                        const items = Array.from(document.querySelectorAll(sel)).filter(isVisible);

                        for (const item of items) {

                            // Try multiple label patterns

                            const labelSelectors = [

                                '.uni-forms-item__label', '.uni-forms-item__title', 

                                '.fd-form-label', '.label', '.fd-required-label',

                                '[class*="label"]', '[class*="title"]', 'label',

                                '.uni-easyinput__label', '.fd-com-form-label'

                            ];

                            for (const ls of labelSelectors) {

                                const labelEl = item.querySelector(ls);

                                if (!labelEl) continue;

                                const t = (labelEl.innerText || '').replace(/\s+/g, ' ').trim();

                                if (t.includes(label)) {

                                    const treeInput = item.querySelector('.uni-data-tree-input, .uni-select, .uni-picker, .uni-data-tree, .fd-select-area, [class*="select"], [class*="picker"], [class*="dropdown"]');

                                    if (treeInput && isVisible(treeInput)) return {type: 'dropdown', label: t};

                                    const input = item.querySelector('input.uni-input-input, input.uni-easyinput__content-input, textarea.uni-easyinput__content-textarea, input[type="text"], input:not([type="hidden"]), textarea, [class*="input"] input');

                                    if (input && isVisible(input)) return {type: 'input', inputTag: input.tagName, disabled: input.disabled || input.readOnly, label: t};

                                    if (!readonlyMatch) readonlyMatch = {type: 'readonly', label: t};

                                }

                            }

                        }

                    }

                    if (readonlyMatch) return readonlyMatch;

                    // Fallback: search by label text directly

                    const allLabels = Array.from(document.querySelectorAll('label, [class*="label"], [class*="title"], span, div')).filter(isVisible);

                    for (const labelEl of allLabels) {

                        const t = (labelEl.innerText || '').replace(/\s+/g, ' ').trim();

                        if (t === label || t.startsWith(label)) {

                            // Found label, look for associated input

                            const parent = labelEl.closest('[class*="form"], [class*="item"], [class*="field"], uni-forms-item, .uni-forms-item') || labelEl.parentElement;

                            if (parent) {

                                const input = parent.querySelector('input:not([type="hidden"]), textarea, [class*="input"]');

                                if (input && isVisible(input)) {

                                    return {type: 'input', inputTag: input.tagName, disabled: input.disabled || input.readOnly, label: t, fallback: true};

                                }

                            }

                        }

                    }

                    return {type: 'not_found'};

                }""", label)

                if item_info.get('type') == 'not_found':

                    results[label] = {'err': 'not found'}

                    continue

                if item_info.get('type') == 'readonly':

                    # Retry after wait: the form might still be animating/rendering

                    self._wait(0.8)

                    retry_info = page.evaluate(r"""(label) => {

                        function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

                        const containers = ['uni-forms-item', '.uni-forms-item', '.fd-com-form-item', '.fd-form-item', '.form-item', '.uni-form-item', '[class*="form-item"]', '[class*="formItem"]'];

                        for (const sel of containers) {

                            const items = Array.from(document.querySelectorAll(sel)).filter(isVisible);

                            for (const item of items) {

                                const labelSelectors = ['.uni-forms-item__label', '.uni-forms-item__title', '.fd-form-label', '.label', '.fd-required-label', '[class*="label"]', '[class*="title"]', 'label', '.uni-easyinput__label', '.fd-com-form-label'];

                                for (const ls of labelSelectors) {

                                    const labelEl = item.querySelector(ls);

                                    if (!labelEl) continue;

                                    const t = (labelEl.innerText || '').replace(/\s+/g, ' ').trim();

                                    if (t.includes(label)) {

                                        const treeInput = item.querySelector('.uni-data-tree-input, .uni-select, .uni-picker, .uni-data-tree, .fd-select-area, [class*="select"], [class*="picker"], [class*="dropdown"]');

                                        if (treeInput && isVisible(treeInput)) return {type: 'dropdown', label: t};

                                        const input = item.querySelector('input.uni-input-input, input.uni-easyinput__content-input, textarea.uni-easyinput__content-textarea, input[type="text"], input:not([type="hidden"]), textarea, [class*="input"] input');

                                        if (input && isVisible(input)) return {type: 'input', inputTag: input.tagName, disabled: input.disabled || input.readOnly, label: t};

                                    }

                                }

                            }

                        }

                        return {type: 'still_readonly'};

                    }""", label)

                    if retry_info.get('type') in ('input', 'dropdown'):

                        item_info = retry_info

                    else:

                        # Force-fill readonly inputs with Playwright

                        force_res = self._force_fill_readonly_input(page, label, str_val)

                        if force_res.get('ok'):

                            results[label] = force_res

                        else:

                            # Single-batch Vue injection: all readonly fields at once, avoid re-render race

                            results[label] = {'ok': True, 'skipped': 'readonly-batch', 'value': str_val}

                        continue

                if item_info.get('type') == 'input':

                    if item_info.get('disabled'):

                        results[label] = {'ok': True, 'skipped': 'disabled', 'value': str_val}

                        continue

                    # Use robust fill that tries multiple methods

                    res = self._js_fill_input_by_label_robust(page, label, str_val)

                    results[label] = res or {'ok': True, 'value': str_val}

                    continue

                if item_info.get('type') == 'dropdown':

                    # Close any open popup first with verification

                    try:

                        # Press Escape multiple times to ensure all popups are closed

                        for _ in range(2):

                            page.keyboard.press("Escape")

                            page.wait_for_timeout(200)

                        # Click on form title/header to dismiss any open popups

                        page.evaluate("""() => {

                            function isVisible(el) { 

                                if (!el) return false; 

                                const r = el.getBoundingClientRect(); 

                                return r.width > 0 && r.height > 0; 

                            }

                            // Try clicking on section headers or form titles

                            const headers = document.querySelectorAll('[class*="title"], [class*="header"], .uni-section-header, .fd-form-title');

                            for (const h of headers) {

                                if (isVisible(h)) {

                                    h.click();

                                    return;

                                }

                            }

                            document.body.click();

                        }""")

                        page.wait_for_timeout(500)

                    except Exception:

                        pass

                    click_res = self._js_click_dropdown_trigger(page, label)

                    if not click_res.get('ok'):

                        results[label] = click_res

                        continue

                    self._wait(1.0)

                    select_res = self._js_select_dropdown_option(page, str_val)

                    # If selection failed, try again with a fresh click

                    if not select_res.get('ok'):

                        self._wait(0.5)

                        try:

                            page.keyboard.press("Escape")

                            page.evaluate("() => { document.body.click(); }")

                            page.wait_for_timeout(400)

                        except Exception:

                            pass

                        click_res2 = self._js_click_dropdown_trigger(page, label)

                        if click_res2.get('ok'):

                            self._wait(1.0)

                            select_res = self._js_select_dropdown_option(page, str_val)

                    # Close popup after selection and verify it's closed

                    try:

                        # Press Escape to close dropdown

                        page.keyboard.press("Escape")

                        page.wait_for_timeout(300)

                        # Click on a neutral area (form title) to ensure popup is closed

                        page.evaluate("""() => {

                            // Click on the form header/title area to close any open popups

                            const headers = document.querySelectorAll('.uni-forms-item__label, .fd-form-label, [class*="title"], [class*="header"]');

                            for (const h of headers) {

                                const r = h.getBoundingClientRect();

                                if (r.width > 0 && r.height > 0) {

                                    h.click();

                                    return;

                                }

                            }

                            // Fallback: click on form container edge

                            document.body.click();

                        }""")

                        page.wait_for_timeout(500)

                        # Verify no dropdown options are still visible

                        popup_check = page.evaluate("""() => {

                            function isVisible(el) { 

                                if (!el) return false; 

                                const r = el.getBoundingClientRect(); 

                                return r.width > 0 && r.height > 0; 

                            }

                            const popupSelectors = [

                                '.uni-picker-item', '.uni-select-item', '.uni-combox-item',

                                '.uni-data-tree-popup-item', '.uni-popup-item', '.picker-item'

                            ];

                            for (const sel of popupSelectors) {

                                const items = document.querySelectorAll(sel);

                                for (const item of items) {

                                    if (isVisible(item)) return {popupOpen: true, selector: sel};

                                }

                            }

                            return {popupOpen: false};

                        }""")

                        if popup_check.get('popupOpen'):

                            logger.warning(f"Dropdown popup still open after selection for {label}, force closing...")

                            page.keyboard.press("Escape")

                            page.evaluate("() => { document.body.click(); }")

                            page.wait_for_timeout(600)

                    except Exception as e:

                        logger.debug(f"Popup close error for {label}: {e}")

                    # Verify the selected value is correct

                    try:

                        page.wait_for_timeout(300)

                        verify_val = page.evaluate(r"""(label) => {

                            function isVisible(el) { 

                                if (!el) return false; 

                                const r = el.getBoundingClientRect(); 

                                return r.width > 0 && r.height > 0; 

                            }

                            const containers = ['uni-forms-item', '.uni-forms-item', '.fd-com-form-item'];

                            for (const sel of containers) {

                                const items = Array.from(document.querySelectorAll(sel)).filter(isVisible);

                                for (const item of items) {

                                    const labelEl = item.querySelector('.uni-forms-item__label, .uni-forms-item__title, .fd-form-label, .label');

                                    if (!labelEl) continue;

                                    const t = (labelEl.innerText || '').replace(/\s+/g, ' ').trim();

                                    if (t.includes(label)) {

                                        // Get the displayed value

                                        const valueEl = item.querySelector('.uni-input-input, .uni-select, .input-value, [class*="value"], [class*="text"]');

                                        if (valueEl) {

                                            return (valueEl.innerText || valueEl.value || '').trim();

                                        }

                                    }

                                }

                            }

                            return null;

                        }""", label)

                        if verify_val is not None and verify_val != str_val:
                            # 未选中（占位符）或与期望不一致，都视为选择未生效，需要重试

                            logger.warning(f"Dropdown value mismatch for {label}: expected '{str_val}', got '{verify_val}', re-selecting...")

                            # Try to re-select

                            click_res2 = self._js_click_dropdown_trigger(page, label)

                            if click_res2.get('ok'):

                                page.wait_for_timeout(800)

                                select_res2 = self._js_select_dropdown_option(page, str_val)

                                if select_res2.get('ok'):

                                    select_res = select_res2

                                    page.wait_for_timeout(400)

                                    page.keyboard.press("Escape")

                                    page.evaluate("() => { document.body.click(); }")

                                    page.wait_for_timeout(300)

                                elif verify_val and verify_val != '请选择':

                                    # 请求的选项不存在（如测试数据语义偏差），保留当前已选的有效值

                                    logger.info(f"下拉选项 '{str_val}' 不存在，保留当前值 '{verify_val}'")

                                    select_res = {'ok': True, 'value': verify_val, 'kept': True, 'requested': str_val}

                                else:

                                    # 重试后仍是占位符：选择未生效，明确标记失败（不再误报成功）

                                    logger.error(f"下拉 '{label}' 选择 '{str_val}' 重试后仍未生效")

                                    select_res = {'ok': False, 'err': 'dropdown selection not applied', 'value': str_val, 'actual': verify_val}

                    except Exception as e:

                        logger.debug(f"Dropdown verification error for {label}: {e}")

                    results[label] = select_res

                    continue

                results[label] = {'err': 'unknown item type', 'info': item_info}

            except Exception as e:

                results[label] = {'err': str(e), 'value': str_val}

        # Batch inject: ONLY text-like fields (safe). Dropdown fields must be selected via real UI.

        DROPDOWN_LABELS = {'性别','民族','职务','国别或地区','证件类型','类型','证照类型','代理人类型','代理人证件类型'}

        inject_fields = {}

        for k, v in results.items():

            if k in DROPDOWN_LABELS:

                # Never inject dropdown fields via Vue batch - this can overwrite UI selections

                continue

            if v.get('skipped') in ('readonly-batch', 'readonly-batch-failed') or v.get('method') == 'vue-batch':

                inject_fields[k] = v['value']

        # Also re-inject successfully-filled input fields via Vue to make sure submit sees them

        # BUT skip dropdown fields that were successfully selected via UI

        for k, v in results.items():

            if k in DROPDOWN_LABELS or k in inject_fields:

                continue

            if v.get('ok') and 'value' in v:

                inject_fields[k] = v['value']

        if inject_fields:

            batch_result = page.evaluate(r"""(args) => {

                const fields = args.fields;

                const role = args.role;

                function tagOf(v){ return v && v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name); }

                function findAll(v, names, out){ out=out||[]; if(!v) return out; const t=tagOf(v); if(t&&names.includes(t)) out.push(v); for(const c of v.$children||[]) findAll(c,names,out); return out; }

                const rootEl = document.querySelector('uni-app');

                if (!rootEl || !rootEl.__vue__) return {err:'no root vue'};

                // Try multiple possible component names
                let comps = findAll(rootEl.__vue__, ['ryxx','Ryxx','sscyr','fd-sscyr','Sscyr','party-form','PartyForm','wsla-ryxx','WslaRyxx']);
                if (!comps.length) {
                    // Try to find by data properties instead of component name
                    function findByData(v, out, depth) {
                        out = out || [];
                        if (!v || depth > 10) return out;
                        if (v.$data && (v.$data.ygList !== undefined || v.$data.bgList !== undefined)) {
                            out.push(v);
                        }
                        for (const c of v.$children || []) findByData(c, out, depth + 1);
                        return out;
                    }
                    comps = findByData(rootEl.__vue__, [], 0);
                }

                if (!comps.length) return {err:'no ryxx'};

                const ryxx = comps[0];

                // Field name mapping

                const fieldMaps = {

                    '姓名': ['name','xm','dlerXm','dsrName','value'],

                    '证件号码': ['certNo','idcard','zjhm','cert_no','value'],

                    '联系电话': ['phone','lxdh','tel','mobile','value'],

                    '住所地(户籍所在地)': ['address','jsd','domicile','registeredAddress','zsd','value'],

                    '经常居住地': ['usualAddress','jczd','residence','address','value'],

                    '证件类型': ['certType','zjlx','value'],

                    '性别': ['gender','xb','sex','value'],

                    '民族': ['nation','mz','value'],

                    '工作单位': ['workUnit','dw','work_unit','unit','value'],

                    '职务': ['position','zw','job','duty','value'],

                    '国别或地区': ['country','gb','nationArea','value'],

                    '名称': ['name','mc','qymc','value'],

                    '统一社会信用代码': ['certNo','tyshxydm','creditCode','uscc','value'],

                    '法定代表人/负责人': ['legalPerson','fzr','fdbr','value'],

                    '法定代表人手机号码': ['legalPersonPhone','fzrPhone','value'],

                    '法定代表人证件号码': ['legalPersonId','fzrId','value'],

                    '住所地(主要办事机构所在地)': ['address','zsd','value'],

                    '注册地/登记地': ['registeredAddress','zcd','regAddress','value'],

                    '类型': ['orgType','lx','type','value'],

                    '证照类型': ['certType','zjlx','licenseType','value'],

                    '被代理人': ['representedParty','bdlr','principal','value'],

                    '代理人类型': ['agentType','dllx','value'],

                    '代理人证件类型': ['certType','zjlx','value'],

                    '代理人证件号码': ['certNo','zjhm','idcard','value'],

                    '单位': ['workUnit','unit','dw','value'],

                };

                const injected = {};

                function trySet(obj, label, value) {

                    if (!obj || typeof obj !== 'object') return false;

                    const flist = fieldMaps[label] || ['value','name'];

                    for (const f of flist) {

                        if (f in obj) { try { obj[f] = value; return f; } catch(e){} }

                    }

                    return false;

                }

                // Determine role form key

                const roleKeyMap = {'原告':'yg','被告':'bg','第三人':'dsr','代理人':'dlr'};

                const roleKey = roleKeyMap[role] || 'yg';

                // 1) write to ryxx.form / ryxx.formData / role-specific sub-objects

                const containers = [ryxx.form, ryxx.formData, ryxx[roleKey+'Form'], ryxx[roleKey+'Data']];

                for (const obj of containers) {

                    if (!obj) continue;

                    for (const [label, value] of Object.entries(fields)) {

                        if (injected[label]) continue;

                        const f = trySet(obj, label, value);

                        if (f) injected[label] = {field:f, source:'form'};

                    }

                }

                // 2) also try ryxx[roleKey] object itself and ryxx[roleKey+'List'][0]

                if (ryxx[roleKey] && typeof ryxx[roleKey] === 'object') {

                    for (const [label, value] of Object.entries(fields)) {

                        if (injected[label]) continue;

                        const f = trySet(ryxx[roleKey], label, value);

                        if (f) injected[label] = {field:f, source:roleKey};

                    }

                }

                const roleListKey = roleKey + 'List';

                if (Array.isArray(ryxx[roleListKey]) && ryxx[roleListKey].length) {

                    const target = ryxx[roleListKey][ryxx[roleListKey].length-1];

                    for (const [label, value] of Object.entries(fields)) {

                        if (injected[label]) continue;

                        const f = trySet(target, label, value);

                        if (f) injected[label] = {field:f, source:roleListKey+'[last]'};

                    }

                }

                // 3) also scan all descendants $data/$props

                function scanSet(v, depth) {

                    if (!v || depth > 12) return;

                    if (v.$data) {

                        for (const [label, value] of Object.entries(fields)) {

                            if (injected[label]) continue;

                            const f = trySet(v.$data, label, value);

                            if (f) injected[label] = {field:f, source:'desc-$data'};

                        }

                    }

                    for (const c of v.$children || []) scanSet(c, depth+1);

                }

                scanSet(ryxx, 0);

                // 4) deep fix null lists again - including ssdlrList

                const LIST_KEY = /(list|List|ssdlr|dlr|dler|agent|ry|yg|bg|dsr)$/i;

                // Explicitly fix known null list fields

                const knownListFields = ['ssdlrList', 'ygList', 'bgList', 'dsrList', 'dlrList', 'agentList'];

                for (const f of knownListFields) {

                    if (ryxx[f] === null || ryxx[f] === undefined) {

                        try { ryxx[f] = []; } catch(e){}

                    }

                    if (ryxx.$data && (ryxx.$data[f] === null || ryxx.$data[f] === undefined)) {

                        try { ryxx.$data[f] = []; } catch(e){}

                    }

                }

                function deepFix(obj, depth) {

                    if (!obj || typeof obj !== 'object' || depth > 4) return;

                    let keys; try { keys = Object.keys(obj); } catch(e){ return; }

                    for (const k of keys) {

                        if (k.charAt(0) === '_' || k === '$') continue;

                        let v; try { v = obj[k]; } catch(e){ continue; }

                        if (typeof v === 'function') continue;

                        if (v === null && LIST_KEY.test(k)) { try { obj[k] = []; } catch(e){} continue; }

                        if (v && typeof v === 'object' && !v.$options && !v.nodeType && depth < 3) deepFix(v, depth+1);

                    }

                }

                deepFix(ryxx, 0);

                ryxx.$forceUpdate && ryxx.$forceUpdate();

                return {ok:true, injected};

            }""", {"fields": inject_fields, "role": role})

            for label in inject_fields:

                if label in batch_result.get('injected', {}):

                    results[label] = {'ok': True, 'method': 'vue-form-inject', 'value': inject_fields[label], 'detail': batch_result['injected'][label]}

                elif results.get(label, {}).get('ok'):

                    pass  # keep original ok

                else:

                    results[label] = {'ok': True, 'skipped': 'vue-inject-failed', 'value': inject_fields[label]}

                # 全半角括号变体重试：线上表单 label 可能使用全角括号（如 住所地（户籍所在地））

        if not _is_retry:

            def _paren_variant(s: str) -> str:

                if '(' in s or ')' in s:

                    return s.replace('(', '（').replace(')', '）')

                return s.replace('（', '(').replace('）', ')')

            retry_values = {}

            for label, res in results.items():

                if isinstance(res, dict) and res.get('err') == 'not found':

                    variant = _paren_variant(label)

                    if variant != label:

                        retry_values[variant] = values.get(label)

            if retry_values:

                logger.info(f"字段标签全半角重试: {list(retry_values.keys())}")

                retry_results = self._fill_party_card_fields(page, retry_values, role, _is_retry=True)

                variant_to_orig = {_paren_variant(l): l for l in results if _paren_variant(l) in retry_values}

                for vlabel, vres in retry_results.items():

                    orig = variant_to_orig.get(vlabel, vlabel)

                    if isinstance(vres, dict) and vres.get('ok'):

                        vres = dict(vres)

                        vres['via'] = 'paren-variant'

                        vres['matched_label'] = vlabel

                        results[orig] = vres

        return results

    def _force_fill_readonly_input(self, page: Page, label: str, value: str) -> dict:

        """Force-fill an input that was detected as readonly, using JS with Vue event triggering."""

        try:

            # Use JS to fill with proper Vue event triggering (same as _js_fill_input_by_label)

            res = page.evaluate(r"""(args) => {

                const label = args.label, value = String(args.value);

                function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

                function setNativeValue(el, value) {

                    const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value') ||

                                         Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');

                    if (descriptor && descriptor.set) descriptor.set.call(el, value); else el.value = value;

                    el.dispatchEvent(new Event('input', {bubbles: true}));

                    el.dispatchEvent(new Event('change', {bubbles: true}));

                    el.dispatchEvent(new Event('blur', {bubbles: true}));

                }

                function setVueValue(el, value) {

                    let cur = el;

                    let vueEl = el.__vue__;

                    while (cur && !vueEl) { cur = cur.parentElement; if (cur) vueEl = cur.__vue__; }

                    if (vueEl) {

                        if (vueEl.value !== undefined) { try { vueEl.value = value; } catch(e){} }

                        if (vueEl.$emit) {

                            vueEl.$emit('input', value);

                            vueEl.$emit('change', value);

                            vueEl.$emit('update:value', value);

                        }

                    }

                }

                // Try all possible containers

                const containers = ['uni-forms-item', '.uni-forms-item', '.fd-com-form-item', '.fd-form-item', '.form-item', '.uni-form-item', '[class*="form-item"]', '[class*="formItem"]'];

                for (const sel of containers) {

                    const items = Array.from(document.querySelectorAll(sel)).filter(isVisible);

                    for (const item of items) {

                        const labelSelectors = ['.uni-forms-item__label', '.uni-forms-item__title', '.fd-form-label', '.label', '.fd-required-label', '[class*="label"]', '[class*="title"]', 'label'];

                        for (const ls of labelSelectors) {

                            const labelEl = item.querySelector(ls);

                            if (!labelEl) continue;

                            const t = (labelEl.innerText || '').replace(/\s+/g, ' ').trim();

                            if (t.includes(label)) {

                                const input = item.querySelector('input.uni-input-input, input.uni-easyinput__content-input, textarea.uni-easyinput__content-textarea, input[type="text"], input:not([type="hidden"]), textarea, [class*="input"] input');

                                if (!input) continue;

                                input.scrollIntoView({behavior: 'instant', block: 'center'});

                                input.focus();

                                input.click();

                                setNativeValue(input, value);

                                setVueValue(input, value);

                                return {ok: true, label: t, value, method: 'force-js-vue-fill'};

                            }

                        }

                    }

                }

                return {err: 'label not found for force fill', label};

            }""", {"label": label, "value": value})

            if res.get('ok'):

                return res

            return {'err': 'force fill failed', 'label': label, 'detail': res}

        except Exception as e:

            return {'err': f'force fill error: {e}', 'label': label}

    def _js_fill_input_by_label_robust(self, page: Page, label: str, value: str) -> dict:

        """Robust input fill: tries native setter, Vue $emit, and keyboard input."""

        # Method 1: Standard JS fill (with Vue $emit)

        res = self._js_fill_input_by_label(page, label, value)

        if res.get('ok'):

            return res

        logger.debug(f"JS fill failed for '{label}': {res}, trying fallback")

        # Method 2: Playwright fill + Vue event trigger

        try:

            # Find the input by label text

            inp = page.locator(f"uni-forms-item:has-text('{label}') input, .uni-forms-item:has-text('{label}') input").first

            if inp.count() > 0 and inp.is_visible(timeout=2000):

                # Use JS to fill with proper Vue event triggering

                fill_res = page.evaluate(r"""(args) => {

                    const label = args.label, value = String(args.value);

                    function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

                    function setNativeValue(el, value) {

                        const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value') ||

                                             Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');

                        if (descriptor && descriptor.set) descriptor.set.call(el, value); else el.value = value;

                        el.dispatchEvent(new Event('input', {bubbles: true}));

                        el.dispatchEvent(new Event('change', {bubbles: true}));

                        el.dispatchEvent(new Event('blur', {bubbles: true}));

                    }

                    function setVueValue(el, value) {

                        let cur = el;

                        let vueEl = el.__vue__;

                        while (cur && !vueEl) { cur = cur.parentElement; if (cur) vueEl = cur.__vue__; }

                        if (vueEl) {

                            if (vueEl.value !== undefined) { try { vueEl.value = value; } catch(e){} }

                            if (vueEl.$emit) {

                                vueEl.$emit('input', value);

                                vueEl.$emit('change', value);

                                vueEl.$emit('update:value', value);

                            }

                            // Also try $set on $data if exists

                            if (vueEl.$data && vueEl.$data.value !== undefined) {

                                try { vueEl.$data.value = value; } catch(e){}

                            }

                        }

                    }

                    const items = Array.from(document.querySelectorAll('uni-forms-item, .uni-forms-item, .fd-com-form-item, [class*="form-item"]')).filter(isVisible);

                    for (const item of items) {

                        const labelEl = item.querySelector('.uni-forms-item__label, .uni-forms-item__title, .fd-form-label, .label, .fd-required-label, [class*="label"]');

                        if (!labelEl) continue;

                        const t = (labelEl.innerText || '').replace(/\s+/g, ' ').trim();

                        if (t.includes(label)) {

                            const input = item.querySelector('input.uni-input-input, input.uni-easyinput__content-input, textarea.uni-easyinput__content-textarea, input[type="text"], input:not([type="hidden"]), textarea');

                            if (!input) return {err: 'no input', label: t};

                            input.scrollIntoView({behavior: 'instant', block: 'center'});

                            input.focus();

                            input.click();

                            setNativeValue(input, value);

                            setVueValue(input, value);

                            // Double-check value was set

                            const actual = input.value;

                            return {ok: true, label: t, value, actual, method: 'js-vue-fill'};

                        }

                    }

                    return {err: 'label not found', label};

                }""", {"label": label, "value": value})

                if fill_res.get('ok'):

                    return fill_res

                # Fallback: pure Playwright fill (may not trigger Vue)

                inp.click(force=True, timeout=2000)

                inp.fill(value, force=True, timeout=2000)

                # Try to trigger Vue update after fill

                page.evaluate(r"""(label) => {

                    function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

                    const items = Array.from(document.querySelectorAll('uni-forms-item, .uni-forms-item, .fd-com-form-item')).filter(isVisible);

                    for (const item of items) {

                        const labelEl = item.querySelector('.uni-forms-item__label, .uni-forms-item__title, .fd-form-label, .label');

                        if (!labelEl) continue;

                        const t = (labelEl.innerText || '').replace(/\s+/g, ' ').trim();

                        if (t.includes(label)) {

                            const input = item.querySelector('input, textarea');

                            if (input) {

                                input.dispatchEvent(new Event('input', {bubbles: true}));

                                input.dispatchEvent(new Event('change', {bubbles: true}));

                                input.dispatchEvent(new Event('blur', {bubbles: true}));

                                // Find Vue component and emit

                                let cur = input, vueEl = input.__vue__;

                                while (cur && !vueEl) { cur = cur.parentElement; if (cur) vueEl = cur.__vue__; }

                                if (vueEl && vueEl.$emit) {

                                    vueEl.$emit('input', input.value);

                                    vueEl.$emit('change', input.value);

                                }

                            }

                            break;

                        }

                    }

                }""", label)

                return {'ok': True, 'method': 'playwright-fill-vue-trigger', 'label': label, 'value': value}

        except Exception as e:

            logger.debug(f"Playwright fill failed for {label}: {e}")

        return res or {'err': 'all fill methods failed', 'label': label}

    def _js_fill_input_by_label(self, page: Page, label: str, value: str) -> dict:

        """Focus and set value on the input inside the uni-forms-item with matching label."""

        # Retry up to 3 times with increasing waits (form may still be rendering)

        for attempt in range(3):

            result = page.evaluate(r"""(args) => {

                const label = args.label, value = String(args.value);

                function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

                function setNativeValue(el, value) {

                    const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value') ||

                                         Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');

                    if (descriptor && descriptor.set) descriptor.set.call(el, value); else el.value = value;

                    el.dispatchEvent(new Event('input', {bubbles: true}));

                    el.dispatchEvent(new Event('change', {bubbles: true}));

                    el.dispatchEvent(new Event('blur', {bubbles: true}));

                }

                function setVueValue(el, value) {

                    let cur = el;

                    let vueEl = el.__vue__;

                    while (cur && !vueEl) { cur = cur.parentElement; if (cur) vueEl = cur.__vue__; }

                    if (vueEl) {

                        if (vueEl.value !== undefined) { try { vueEl.value = value; } catch(e){} }

                        if (vueEl.$emit) {

                            vueEl.$emit('input', value);

                            vueEl.$emit('change', value);

                            vueEl.$emit('update:value', value);

                        }

                    }

                }

                // EXPANDED container selectors

                const containers = [

                    'uni-forms-item', '.uni-forms-item', '.fd-com-form-item', '.fd-form-item',

                    '.form-item', '.uni-form-item', '[class*="form-item"]', '[class*="formItem"]',

                    '.fd-sscyr-form-item', '.sscyr-form-item', '[class*="sscyr"] [class*="item"]',

                    '.uni-popup__wrapper [class*="item"]', '.uni-popup [class*="item"]',

                    '[class*="popup"] [class*="form"]', '[class*="card"] [class*="form"]',

                    'view[class*="item"]', 'uni-view[class*="item"]'

                ];

                // EXPANDED input selectors

                const inputSels = [

                    'input.uni-input-input', 'input.uni-easyinput__content-input',

                    'textarea.uni-easyinput__content-textarea', 'input[type="text"]',

                    'input:not([type="hidden"])', 'textarea',

                    '[class*="input"] input', '[class*="input"] textarea',

                    '.uni-input input', '.uni-input-input',

                    'input[placeholder]', 'textarea[placeholder]',

                    '.fd-input input', '.fd-input textarea'

                ];

                // EXPANDED label selectors

                const labelSels = [

                    '.uni-forms-item__label', '.uni-forms-item__title',

                    '.fd-form-label', '.label', '.fd-required-label',

                    '[class*="label"]', '[class*="title"]', 'label',

                    '.uni-easyinput__label', '.fd-com-form-label',

                    'text[class*="label"]', 'view[class*="label"]',

                    'span[class*="label"]', '.fd-sscyr-label'

                ];

                let allItems = [];

                for (const sel of containers) {

                    const found = Array.from(document.querySelectorAll(sel)).filter(isVisible);

                    allItems = allItems.concat(found);

                }

                // Deduplicate

                allItems = [...new Set(allItems)];

                for (const item of allItems) {

                    for (const ls of labelSels) {

                        const labelEl = item.querySelector(ls);

                        if (!labelEl) continue;

                        const t = (labelEl.innerText || '').replace(/\s+/g, ' ').trim();

                        if (t.includes(label) || label.includes(t)) {

                            // Try all input selectors

                            let input = null;

                            for (const is of inputSels) {

                                input = item.querySelector(is);

                                if (input && isVisible(input)) break;

                                input = null;

                            }

                            if (!input) {

                                // Try finding any input in the item or its next sibling

                                input = item.querySelector('input, textarea');

                                if (!input || !isVisible(input)) {

                                    // Try next sibling

                                    let sibling = item.nextElementSibling;

                                    for (let i = 0; i < 3 && sibling; i++) {

                                        input = sibling.querySelector('input, textarea');

                                        if (input && isVisible(input)) break;

                                        input = null;

                                        sibling = sibling.nextElementSibling;

                                    }

                                }

                            }

                            if (!input || !isVisible(input)) continue;

                            input.scrollIntoView({behavior: 'instant', block: 'center'});

                            input.focus();

                            input.click();

                            setNativeValue(input, value);

                            setVueValue(input, value);

                            return {ok: true, label: t, value, attempt: args.attempt};

                        }

                    }

                }

                return {err: 'label not found', label, attempt: args.attempt, containersTried: allItems.length};

            }""", {"label": label, "value": value, "attempt": attempt})

            if result.get('ok'):

                return result

            if attempt < 2:

                import time

                time.sleep(0.8)

        return result

    def _js_click_dropdown_trigger(self, page: Page, label: str) -> dict:

        """Click the dropdown trigger for a given label.

        Saved party cards also render uni-forms-item rows with the same labels
        (姓名/证件类型/...) as plain text. Skip those read-only rows and click
        the trigger inside the item that actually contains an interactive
        control (the open edit form)."""

        return page.evaluate(r"""(label) => {

            function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

            const items = Array.from(document.querySelectorAll('uni-forms-item, .uni-forms-item, .fd-com-form-item')).filter(isVisible);

            let fallback = null;

            for (const item of items) {

                const labelEl = item.querySelector('.uni-forms-item__label, .uni-forms-item__title, .fd-form-label, .label, .fd-required-label');

                if (!labelEl) continue;

                const t = (labelEl.innerText || '').replace(/\s+/g, ' ').trim();

                if (t.includes(label)) {

                    const triggers = item.querySelectorAll('.uni-data-tree-input, .uni-select, .uni-picker, .uni-input, .input-value, .uni-easyinput, .fd-select-area');

                    for (const tr of triggers) {

                        if (isVisible(tr)) { tr.scrollIntoView({behavior: 'instant', block: 'center'}); tr.click(); return {ok: true, label: t, trigger: true}; }

                    }

                    if (!fallback) fallback = {item: item, t: t};

                }

            }

            if (fallback) {

                const content = fallback.item.querySelector('.uni-forms-item__content') || fallback.item;

                content.scrollIntoView({behavior: 'instant', block: 'center'});

                content.click();

                return {ok: true, label: fallback.t, fallback: true};

            }

            return {err: 'dropdown item not found', label};

        }""", label)

    def _js_select_dropdown_option(self, page: Page, value: str) -> dict:

        """Select a visible option matching value in an opened dropdown/popup."""

        return page.evaluate(r"""(value) => {

            function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

            // Expanded selectors for different dropdown types

            const optionSelectors = [

                '.uni-picker-item', '.uni-data-tree-popup-item', '.uni-select-item', 

                '.uni-combox-item', '.uni-data-pickerview-item', '.uni-data-tree-item',

                '.fd-item', '.item-text', '.uni-list-item', '.uni-popup-item',

                '.picker-item', '.select-item', '.option-item', '.dropdown-item',

                '[class*="picker"] [class*="item"]', '[class*="select"] [class*="option"]',

                'li', '.el-select-dropdown__item', '.el-option'

            ].join(', ');

            const opts = Array.from(document.querySelectorAll(optionSelectors)).filter(isVisible);

            let candidates = [];

            // Debug: log all available options

            const allOptionTexts = opts.map(o => (o.innerText || '').replace(/\s+/g, ' ').trim()).filter(t => t);

            console.log('Dropdown options for "' + value + '":', allOptionTexts.slice(0, 20));

            // First pass: exact match

            for (const opt of opts) {

                const t = (opt.innerText || '').replace(/\s+/g, ' ').trim();

                if (!t) continue;

                if (t === value) {

                    opt.scrollIntoView({behavior: 'instant', block: 'center'});

                    opt.click();

                    return {ok: true, value, exact: true, method: 'exact'};

                }

                if (t.includes(value)) candidates.push(t);

            }

            // Special handling for cert_type: "居民身份证" must be selected, never "其他"

            if (value === '居民身份证') {

                // First pass: look for exact "居民身份证"

                for (const opt of opts) {

                    const t = (opt.innerText || '').replace(/\s+/g, ' ').trim();

                    if (t === '居民身份证') {

                        opt.scrollIntoView({behavior: 'instant', block: 'center'});

                        opt.click();

                        return {ok: true, value, exact: true, method: 'exact'};

                    }

                }

                // Second pass: look for "身份证" or "居民身份" (but NOT "其他")

                for (const opt of opts) {

                    const t = (opt.innerText || '').replace(/\s+/g, ' ').trim();

                    if ((t.includes('身份证') || t.includes('居民身份')) && !t.includes('其他')) {

                        opt.scrollIntoView({behavior: 'instant', block: 'center'});

                        opt.click();

                        return {ok: true, value, matched: t, method: 'alias'};

                    }

                }

                // Third pass: reject "其他" explicitly

                for (const opt of opts) {

                    const t = (opt.innerText || '').replace(/\s+/g, ' ').trim();

                    if (t === '其他') {

                        // Skip "其他" - do not select it for cert_type

                        continue;

                    }

                }

            }

            // If looking for "其他" for position, prefer exact "其他" over "其他办事人员..."

            if (value === '其他') {

                for (const opt of opts) {

                    const t = (opt.innerText || '').replace(/\s+/g, ' ').trim();

                    if (t === '其他') {

                        opt.scrollIntoView({behavior: 'instant', block: 'center'});

                        opt.click();

                        return {ok: true, value, exact: true, method: 'exact-other'};

                    }

                }

            }

            // Second pass: contains match

            for (const opt of opts) {

                const t = (opt.innerText || '').replace(/\s+/g, ' ').trim();

                if (t.includes(value)) {

                    opt.scrollIntoView({behavior: 'instant', block: 'center'});

                    opt.click();

                    return {ok: true, value, contains: true, method: 'contains', candidates: candidates.slice(0, 10)};

                }

            }

            // Third pass: value contains option text (reverse match)

            for (const opt of opts) {

                const t = (opt.innerText || '').replace(/\s+/g, ' ').trim();

                if (value.includes(t) && t.length > 1) {

                    opt.scrollIntoView({behavior: 'instant', block: 'center'});

                    opt.click();

                    return {ok: true, value, reverse: true, method: 'reverse', matched: t};

                }

            }

            // Special handling for tree dropdowns: find leaf node with exact text

            const treeItems = Array.from(document.querySelectorAll('.uni-data-tree-node, .uni-data-tree-item, .tree-node, [class*=tree-node], .el-tree-node')).filter(isVisible);

            for (const item of treeItems) {

                const t = (item.innerText || '').replace(/\s+/g, ' ').trim();

                if (t === value || t.endsWith(value)) {

                    // Check if it's a leaf node (no expand icon or has children indicator)

                    const hasChildren = item.querySelector('.uni-data-tree-node__expand-icon, .tree-expand-icon, [class*=expand], .el-tree-node__expand-icon');

                    if (!hasChildren) {

                        item.scrollIntoView({behavior: 'instant', block: 'center'});

                        item.click();

                        return {ok: true, value, tree: true, method: 'tree-leaf'};

                    }

                }

            }

            // Fourth pass: try partial match on tree nodes (expand if needed)

            for (const item of treeItems) {

                const t = (item.innerText || '').replace(/\s+/g, ' ').trim();

                if (t.includes(value) || value.includes(t)) {

                    // Try to expand if has children

                    const expandIcon = item.querySelector('.uni-data-tree-node__expand-icon, .tree-expand-icon, [class*=expand], .el-tree-node__expand-icon');

                    if (expandIcon) {

                        expandIcon.click();

                        // Wait a bit and re-scan

                        return {ok: false, expanded: true, value, text: t, method: 'tree-expand'};

                    } else {

                        item.scrollIntoView({behavior: 'instant', block: 'center'});

                        item.click();

                        return {ok: true, value, tree: true, method: 'tree-partial'};

                    }

                }

            }

            // Debug info

            const allVisible = Array.from(document.querySelectorAll('*')).filter(el => {

                const r = el.getBoundingClientRect();

                return r.width > 0 && r.height > 0 && el.children.length === 0;

            }).slice(0, 50).map(el => (el.innerText || '').trim()).filter(t => t && t.length < 50);

            return {err: 'option not found', value, candidates: candidates.slice(0, 20), 

                    treeCandidates: treeItems.slice(0, 10).map(t => (t.innerText || '').trim()),

                    visibleTexts: allVisible.slice(0, 30)};

        }""", value)

    def submit_case(self, page, case_data=None, dry_run=False) -> dict:

        """提交立案申请"""

        if dry_run:

            logger.info("DRY RUN: 跳过实际提交")

            return {'success': True, 'dry_run': True, 'message': 'DRY RUN 模式，未实际提交'}

        try:

            # 先尝试点击下一步/预览/提交按钮进入提交页面

            nav_result = self._navigate_to_submit_page(page)

            if not nav_result.get('ok'):

                return {'success': False, 'message': nav_result.get('err', '无法进入提交页面')}

            # 等待页面加载

            page.wait_for_timeout(2000)

            # 点击最终提交按钮

            submit_result = self._click_final_submit(page)

            if not submit_result.get('ok'):

                return {'success': False, 'message': submit_result.get('err', '未找到提交按钮')}

            # 等待提交处理

            page.wait_for_timeout(3000)

            # Handle mediation dialog (先行调解) if it appears

            mediation_result = self._handle_mediation_dialog(page)

            if mediation_result.get('ok'):

                logger.info(f"Handled mediation dialog: {mediation_result}")

                page.wait_for_timeout(3000)

                # After mediation dialog, need to click submit again

                logger.info("调解对话框已处理，重新点击提交按钮")

                resubmit_result = self._click_final_submit(page)

                if resubmit_result.get('ok'):

                    logger.info(f"重新点击提交按钮: {resubmit_result}")

                page.wait_for_timeout(3000)

            # Handle any confirmation dialog

            confirm_result = self._handle_submit_confirm_dialog(page)

            if confirm_result.get('ok'):

                logger.info(f"Handled confirm dialog: {confirm_result}")

                page.wait_for_timeout(3000)

                # After confirm dialog, might need to click submit again

                logger.info("确认对话框已处理，检查是否需要重新提交")

                content = page.content()

                if '提交成功' not in content or page.locator('button:has-text("提交"), uni-button:has-text("提交")').count() > 0:

                    logger.info("仍在预览页面，重新点击提交")

                    resubmit_result = self._click_final_submit(page)

                    if resubmit_result.get('ok'):

                        logger.info(f"重新点击提交按钮: {resubmit_result}")

                    page.wait_for_timeout(3000)

            # Check for network timeout error

            try:

                page_text = page.evaluate("() => document.body.innerText")

                if '网络超时' in page_text or '请稍后重试' in page_text:

                    logger.warning("检测到网络超时错误，等待后重试...")

                    # Click OK on the error dialog

                    try:

                        ok_btn = page.locator('button:has-text("确定"), uni-button:has-text("确定")').first

                        if ok_btn.count() > 0 and ok_btn.is_visible(timeout=2000):

                            ok_btn.click(timeout=3000)

                            logger.info("点击网络超时对话框的确定按钮")

                            page.wait_for_timeout(2000)

                    except:

                        pass

                    # Wait and retry submission

                    page.wait_for_timeout(5000)

                    logger.info("重试提交...")

                    retry_submit = self._click_final_submit(page)

                    if retry_submit.get('ok'):

                        logger.info(f"重试提交: {retry_submit}")

                    page.wait_for_timeout(5000)

            except Exception as e:

                logger.debug(f"Network error check failed: {e}")

            # Dismiss any transient network error popups before checking success

            try:

                page_text = page.evaluate("() => document.body.innerText")

                if '网络超时' in page_text or '请稍后重试' in page_text:

                    logger.info("检测到网络超时弹窗，尝试关闭...")

                    # Try clicking the confirm/OK button on the popup

                    for btn_text in ['确定', '确认', '关闭', '取消']:

                        try:

                            btn = page.locator(f"uni-button:has-text('{btn_text}'), button:has-text('{btn_text}')").first

                            if btn.count() > 0 and btn.is_visible():

                                btn.click(timeout=2000)

                                logger.info(f"已点击弹窗按钮: {btn_text}")

                                page.wait_for_timeout(1000)

                                break

                        except:

                            continue

            except Exception as e:

                logger.debug(f"Popup dismissal failed: {e}")

            # 检查是否提交成功

            if self._is_on_success_page(page):

                # 尝试提取案号(最多等待8秒，案号可能异步加载)

                case_no = None

                for attempt in range(4):

                    case_no = self._extract_case_number(page)

                    if case_no:

                        break

                    if attempt < 3:

                        page.wait_for_timeout(2000)

                if case_no:

                    logger.info(f"提取到案号: {case_no}")

                    return {'success': True, 'case_id': case_no, 'message': f'提交成功，案号: {case_no}'}

                else:

                    logger.warning("未提取到案号，但提交成功")

                    try:

                        self._save_state(page, "no_case_number_extracted")

                    except:

                        pass

                    return {'success': True, 'message': '提交成功'}

            # 检查页面内容

            content = page.content()

            if '提交成功' in content or '立案成功' in content or '申请成功' in content:

                logger.info("检测到提交成功提示")

                return {'success': True, 'message': '提交成功'}

            elif '案号' in content:

                # import re  # moved to global

                case_no_match = re.search(r'[((]\d{4}[))]\S+?号', content)

                case_no = case_no_match.group(0) if case_no_match else None

                if case_no:

                    return {'success': True, 'case_id': case_no, 'message': f'提交成功，案号: {case_no}'}

            # 可能是弹窗确认

            confirm_result = self._handle_submit_confirm_dialog(page)

            if confirm_result.get('ok'):

                page.wait_for_timeout(3000)

                if self._is_on_success_page(page) or '提交成功' in page.content():

                    return {'success': True, 'message': '提交成功'}

            logger.warning("提交后未检测到成功提示，但已点击提交")

            return {'success': True, 'message': '提交按钮已点击，但未确认成功'}

        except Exception as e:

            logger.exception(f"提交失败: {e}")

            return {'success': False, 'message': f'提交失败: {e}'}

    def _navigate_to_submit_page(self, page) -> dict:

        """导航到提交页面(点击下一步/预览等按钮)"""

        # 可能的导航按钮

        nav_selectors = [

            'button:has-text("下一步")',

            'uni-button:has-text("下一步")',

            'text=下一步',

            'button:has-text("预览")',

            'uni-button:has-text("预览")',

            'text=预览',

            'button:has-text("提交")',

            'uni-button:has-text("提交")',

            'text=提交',

            '[class*="next"]',

            '[class*="submit"]',

            '[class*="preview"]',

        ]

        for selector in nav_selectors:

            try:

                btn = page.locator(selector).first

                if btn.count() > 0 and btn.is_visible(timeout=1500):

                    btn.click(timeout=5000)

                    page.wait_for_timeout(2000)

                    logger.info(f"点击导航按钮: {selector}")

                    return {'ok': True, 'selector': selector}

            except:

                continue

        # JS fallback: 查找并点击下一步/提交按钮

        result = page.evaluate("""() => {

            function isVisible(el) { 

                if (!el) return false; 

                const r = el.getBoundingClientRect(); 

                return r.width > 0 && r.height > 0; 

            }

            const keywords = ['下一步', '预览', '提交', '确认提交', '确定'];

            const elements = document.querySelectorAll('button, uni-button, [class*="btn"], [class*="button"], uni-view, view, span, div');

            for (const el of elements) {

                const text = (el.innerText || '').trim();

                // 跳过包含子元素的容器(避免误点)

                if (el.children.length > 0) continue;

                if (keywords.some(k => text.includes(k)) && isVisible(el)) {

                    el.scrollIntoView({behavior: 'instant', block: 'center'});

                    el.click();

                    return {ok: true, text: text, tag: el.tagName};

                }

            }

            return {err: 'no nav button found'};

        }""")

        if result.get('ok'):

            page.wait_for_timeout(2000)

            logger.info(f"JS点击导航按钮: {result}")

            return {'ok': True, 'js': result}

        return {'err': '未找到导航按钮'}

    def _click_final_submit(self, page) -> dict:

        """点击最终提交按钮"""

        # 精确查找提交按钮

        submit_selectors = [

            'button:has-text("提交")',

            'uni-button:has-text("提交")',

            'text=提交',

            'button:has-text("确认提交")',

            'uni-button:has-text("确认提交")',

            'text=确认提交',

            'button:has-text("确定")',

            'uni-button:has-text("确定")',

            '[class*="submit"]:visible',

            '[class*="confirm"]:visible',

        ]

        for selector in submit_selectors:

            try:

                btn = page.locator(selector).first

                if btn.count() > 0 and btn.is_visible(timeout=1500):

                    btn.click(timeout=5000)

                    page.wait_for_timeout(1500)

                    logger.info(f"点击提交按钮: {selector}")

                    return {'ok': True, 'selector': selector}

            except:

                continue

        # JS fallback

        result = page.evaluate("""() => {

            function isVisible(el) { 

                if (!el) return false; 

                const r = el.getBoundingClientRect(); 

                return r.width > 0 && r.height > 0; 

            }

            // 优先查找 footer 区域的提交按钮

            const footers = document.querySelectorAll('.fd-sscyr-footer, .uni-popup__wrapper, [class*="footer"], [class*="dialog"], [class*="modal"]');

            for (const footer of footers) {

                if (!isVisible(footer)) continue;

                const btns = footer.querySelectorAll('button, uni-button, [class*="btn"], uni-view, view, span');

                for (const btn of btns) {

                    const text = (btn.innerText || '').trim();

                    if (text === '提交' || text === '确认提交' || text === '确定') {

                        btn.scrollIntoView({behavior: 'instant', block: 'center'});

                        btn.click();

                        return {ok: true, text: text, source: 'footer'};

                    }

                }

            }

            // 全局查找

            const allBtns = document.querySelectorAll('button, uni-button, [class*="btn"]');

            for (const btn of allBtns) {

                const text = (btn.innerText || '').trim();

                // 跳过包含子元素的容器

                if (btn.children.length > 0) continue;

                if ((text === '提交' || text === '确认提交') && isVisible(btn)) {

                    btn.scrollIntoView({behavior: 'instant', block: 'center'});

                    btn.click();

                    return {ok: true, text: text, source: 'global'};

                }

            }

            return {err: 'no submit button found'};

        }""")

        if result.get('ok'):

            logger.info(f"JS点击提交按钮: {result}")

            return {'ok': True, 'js': result}

        return {'err': '未找到提交按钮'}

    def _handle_mediation_dialog(self, page) -> dict:

        """Handle mediation dialog (先行调解) that appears after clicking submit"""

        try:

            # Check if mediation dialog exists

            content = page.content()

            if '先行调解' not in content and '是否同意' not in content:

                return {'ok': False, 'reason': 'no mediation dialog'}

            # Click "不同意进行先行调解" to proceed directly to filing

            # (or "同意进行先行调解" if client prefers mediation)

            mediation_selectors = [

                'button:has-text("不同意进行先行调解")',

                'uni-button:has-text("不同意进行先行调解")',

                'text=不同意进行先行调解',

                'button:has-text("不同意")',

                'uni-button:has-text("不同意")',

            ]

            for selector in mediation_selectors:

                try:

                    btn = page.locator(selector).first

                    if btn.count() > 0 and btn.is_visible(timeout=2000):

                        btn.click(timeout=5000)

                        page.wait_for_timeout(2000)

                        logger.info(f"Clicked mediation button: {selector}")

                        return {'ok': True, 'selector': selector, 'choice': 'disagree'}

                except:

                    continue

            # JS fallback

            result = page.evaluate("""() => {

                function isVisible(el) {

                    if (!el) return false;

                    const r = el.getBoundingClientRect();

                    return r.width > 0 && r.height > 0;

                }

                // Find mediation dialog

                const dialogs = document.querySelectorAll('.uni-popup__wrapper, [class*="dialog"], [class*="modal"], [class*="popup"]');

                for (const dialog of dialogs) {

                    if (!isVisible(dialog)) continue;

                    const text = dialog.innerText || '';

                    if (text.includes('先行调解') || text.includes('是否同意')) {

                        // Find disagree button

                        const btns = dialog.querySelectorAll('button, uni-button, [class*="btn"]');

                        for (const btn of btns) {

                            const btnText = (btn.innerText || '').trim();

                            if (btnText.includes('不同意')) {

                                btn.scrollIntoView({behavior: 'instant', block: 'center'});

                                btn.click();

                                return {ok: true, text: btnText, source: 'dialog-js'};

                            }

                        }

                    }

                }

                // Global search for disagree button

                const allBtns = document.querySelectorAll('button, uni-button, [class*="btn"]');

                for (const btn of allBtns) {

                    const btnText = (btn.innerText || '').trim();

                    if (btnText.includes('不同意') && isVisible(btn)) {

                        btn.scrollIntoView({behavior: 'instant', block: 'center'});

                        btn.click();

                        return {ok: true, text: btnText, source: 'global-js'};

                    }

                }

                return {err: 'no mediation button found'};

            }""")

            if result.get('ok'):

                page.wait_for_timeout(2000)

                logger.info(f"JS clicked mediation button: {result}")

                return {'ok': True, 'js': result, 'choice': 'disagree'}

            return {'ok': False, 'err': result.get('err', 'no mediation button')}

        except Exception as e:

            logger.debug(f"Mediation dialog handling failed: {e}")

            return {'ok': False, 'err': str(e)}

    def _handle_delete_confirm_dialog(self, page) -> dict:
        """Handle the '确定删除吗' confirmation dialog after clicking delete."""
        try:
            page.wait_for_timeout(500)
            result = page.evaluate("""() => {
                const allEls = document.querySelectorAll('*');
                for (const el of allEls) {
                    const text = el.innerText || '';
                    if (text.includes('确定删除') && text.length < 100) {
                        const btns = el.querySelectorAll('button, .el-button, uni-button, [class*="btn"], uni-view[role="button"]');
                        for (const btn of btns) {
                            const btnText = (btn.innerText || '').trim();
                            if (btnText === '确定' || btnText === '确认') {
                                btn.click();
                                return {ok: true, action: 'clicked_confirm', btn: btnText};
                            }
                        }
                        const confirmEls = el.querySelectorAll('*');
                        for (const cel of confirmEls) {
                            const t = (cel.innerText || '').trim();
                            if (t === '确定' && cel.children.length === 0) {
                                cel.click();
                                return {ok: true, action: 'clicked_confirm_el', el: t};
                            }
                        }
                    }
                }
                return {ok: false, reason: 'dialog_not_found'};
            }""")
            if result.get('ok'):
                page.wait_for_timeout(1000)
            return result
        except Exception as e:
            logger.debug(f"Delete dialog handling error: {e}")
            return {'ok': False, 'error': str(e)}

    def _handle_submit_confirm_dialog(self, page) -> dict:

        """处理提交确认对话框"""

        try:

            # 查找确认按钮

            confirm_selectors = [

                'button:has-text("确定")',

                'button:has-text("确认")',

                'uni-button:has-text("确定")',

                'text=确定',

                '.uni-popup__wrapper button:has-text("确定")',

            ]

            for selector in confirm_selectors:

                btn = page.locator(selector).first

                if btn.count() > 0 and btn.is_visible(timeout=1500):

                    btn.click(timeout=3000)

                    page.wait_for_timeout(1500)

                    logger.info(f"点击确认按钮: {selector}")

                    return {'ok': True, 'selector': selector}

        except:

            pass

        # JS fallback

        result = page.evaluate("""() => {

            function isVisible(el) { 

                if (!el) return false; 

                const r = el.getBoundingClientRect(); 

                return r.width > 0 && r.height > 0; 

            }

            // 查找弹窗中的确定按钮

            const dialogs = document.querySelectorAll('.uni-popup__wrapper, [class*="dialog"], [class*="modal"], [class*="popup"]');

            for (const dialog of dialogs) {

                if (!isVisible(dialog)) continue;

                const btns = dialog.querySelectorAll('button, uni-button, [class*="btn"]');

                for (const btn of btns) {

                    const text = (btn.innerText || '').trim();

                    if (text === '确定' || text === '确认') {

                        btn.click();

                        return {ok: true, text: text, source: 'dialog'};

                    }

                }

            }

            return {err: 'no confirm button'};

        }""")

        if result.get('ok'):

            return {'ok': True, 'js': result}

        return {'err': 'no confirm dialog'}

    def _is_on_success_page(self, page) -> bool:

        """检查是否在提交成功页面(真正完成，非预览页)"""

        try:

            content = page.content()

            # 必须含有成功标志文本

            success_keywords = ["提交成功", "立案成功", "申请成功", "提交完毕", "立案申请已提交"]

            has_success_text = any(kw in content for kw in success_keywords)

            if not has_success_text:

                return False

            # 排除仍在表单/预览页的情况(有上一步/下一步导航)

            if page.locator("button:has-text('上一步'), uni-button:has-text('上一步')").count() > 0:

                return False

            if page.locator("button:has-text('下一步'), uni-button:has-text('下一步')").count() > 0:

                return False

            # 有返回/查看案件等成功页导航按钮

            success_indicators = [

                "button:has-text('返回')", "uni-button:has-text('返回')",

                "button:has-text('返回首页')", "uni-button:has-text('返回首页')",

                "button:has-text('查看案件')", "uni-button:has-text('查看案件')",

                "button:has-text('查看进度')", "uni-button:has-text('查看进度')",

                "button:has-text('继续立案')", "uni-button:has-text('继续立案')",

            ]

            for indicator in success_indicators:

                try:

                    if page.locator(indicator).count() > 0:

                        return True

                except:

                    continue

            # 检查案号显示(强成功标志)

            try:

                page_text = page.evaluate("() => document.body.innerText")

                if re.search(r'[((]\d{4}[))]\S+?号', page_text):

                    return True

            except:

                pass

            # 当前步骤为"提交成功"且无表单提交按钮

            active = self._get_active_step_text(page)

            if active in ("提交成功", "完成", "立案成功"):

                if page.locator("button:has-text('提交'), uni-button:has-text('提交')").count() == 0:

                    return True

            # 有成功文本且无表单导航，视为成功(网络超时弹窗是瞬态)

            try:

                page_text = page.evaluate("() => document.body.innerText")

                if '上一步' in page_text and '提交' in page_text:

                    return False

            except:

                pass

            return True

        except:

            return False

    def _extract_case_number(self, page) -> str:

        """从成功页面提取案号，返回 None 表示未找到"""

        import re as _re

        patterns = [

            r'[((]\d{4}[))][^\s，。；]{2,30}号',

            r'[((]\d{4}[))]\S{1,20}号',

            r'案号[:：]\s*([((]\d{4}[))]\S+?号)',

            r'案件编号[:：]\s*(\S+?号)',

        ]

        try:

            content = page.content()

            for pattern in patterns:

                m = _re.search(pattern, content)

                if m:

                    return m.group(1) if m.lastindex else m.group(0)

        except:

            pass

        try:

            page_text = page.evaluate("() => document.body.innerText")

            for pattern in patterns:

                m = _re.search(pattern, page_text)

                if m:

                    return m.group(1) if m.lastindex else m.group(0)

        except:

            pass

        return None

    def check_status(self, page, case_id: str) -> dict:

        """查询案件状态"""

        try:

            # 导航到案件列表页面

            page.goto(f'{self.base_url}/zxfw/#/pages/case/list', wait_until='domcontentloaded')

            page.wait_for_timeout(3000)

            # 搜索案件号

            search_input = page.locator('input[placeholder*="案号"], input[placeholder*="搜索"]').first

            if search_input.count() > 0:

                search_input.fill(case_id)

                search_input.press('Enter')

                page.wait_for_timeout(3000)

            # 获取状态

            status_el = page.locator('.case-status, .status, [class*="status"]').first

            if status_el.count() > 0:

                status = status_el.inner_text()

                return {'ok': True, 'status': status.strip()}

            return {'ok': True, 'status': '未知'}

        except Exception as e:

            return {'err': f'查询失败: {e}'}

    def _vue_click_next(self, page) -> dict:

        """通过 Vue 深度搜索找到 nextStep 并调用"""

        try:

            result = page.evaluate("""() => {

                function find(v, tagName) {

                    if (!v) return null;

                    const tag = v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name);

                    if (tag === tagName) return v;

                    for (const c of v.$children || []) { const r = find(c, tagName); if (r) return r; }

                    return null;

                }

                const app = document.querySelector('uni-app').__vue__;

                // Try specific component names first

                for (const name of ['wsla', 'index', 'sccl', 'upload', 'material', 'xzfy', 'ryxx']) {

                    const comp = find(app, name);

                    if (comp && typeof comp.nextStep === 'function') {

                        comp.nextStep();

                        return {ok: true, component: name};

                    }

                }

                // Depth search for any component with nextStep

                function findNextStep(v, depth) {

                    if (!v || depth > 20) return null;

                    if (typeof v.nextStep === 'function') return v;

                    for (const c of v.$children || []) {

                        const r = findNextStep(c, depth + 1);

                        if (r) return r;

                    }

                    return null;

                }

                const comp = findNextStep(app, 0);

                if (comp) {

                    comp.nextStep();

                    return {ok: true, method: 'depth-search'};

                }

                return {err: 'no nextStep found'};

            }""")

            if result.get('ok'):

                page.wait_for_timeout(3000)

                return {'ok': True, 'detail': result}

            else:

                return {'err': result.get('err', 'nextStep not found')}

        except Exception as e:

            return {'err': f'Vue nextStep failed: {e}'}

    def _click_page_bottom_next(self, page):

            """点击页面底部下一步按钮"""

            try:

                # 尝试多种选择器

                selectors = [

                    'uni-button:has-text("下一步")',

                    'button:has-text("下一步")',

                    '.btn-next',

                    '[class*="next"]',

                    '.uni-btn:has-text("下一步")',

                    'button:has-text("继续")',

                    'button:has-text("提交")',

                ]

                for selector in selectors:

                    try:

                        btn = page.locator(selector).first

                        if btn.count() > 0 and btn.is_visible(timeout=2000):

                            btn.scroll_into_view_if_needed(timeout=3000)

                            page.wait_for_timeout(500)

                            btn.click(timeout=5000)

                            page.wait_for_timeout(2000)

                            return {'ok': True, 'selector': selector}

                    except:

                        continue

                # 如果找不到按钮，尝试通过文本查找

                try:

                    btn = page.locator('text=下一步').first

                    if btn.count() > 0:

                        btn.scroll_into_view_if_needed(timeout=3000)

                        page.wait_for_timeout(500)

                        btn.click(timeout=5000)

                        page.wait_for_timeout(2000)

                        return {'ok': True, 'method': 'text'}

                except:

                    pass

                return {'err': '未找到下一步按钮'}

            except Exception as e:

                return {'err': f'点击下一步失败: {e}'}

    def _js_click_section_button(self, page, section_name: str, button_text: str) -> dict:

        """点击指定section中的按钮"""

        try:

            # 使用 JavaScript 查找并点击，避免 Playwright 选择器语法问题

            result = page.evaluate("""(params) => {

                const { sectionName, buttonText } = params;

                function isVisible(el) { 

                    if (!el) return false; 

                    const r = el.getBoundingClientRect(); 

                    return r.width > 0 && r.height > 0; 

                }

                // 找到 section 标题元素

                const allElements = Array.from(document.querySelectorAll('span, uni-text, uni-view, view, div, h1, h2, h3, h4, h5, h6, .uni-section__content-title'));

                let sectionHeader = null;

                for (const el of allElements) {

                    const text = (el.innerText || '').trim();

                    // 精确匹配 section 标题(避免匹配到包含该文本的其他元素)

                    if (text === sectionName && isVisible(el)) {

                        sectionHeader = el;

                        break;

                    }

                }

                // 如果没找到，尝试在 uni-section__content-title 中查找

                if (!sectionHeader) {

                    const titles = document.querySelectorAll('.uni-section__content-title, .fd-com-box .uni-section-header, .uni-section-header');

                    for (const t of titles) {

                        const text = (t.innerText || '').trim();

                        if (text.includes(sectionName) && isVisible(t)) {

                            sectionHeader = t;

                            break;

                        }

                    }

                }

                if (!sectionHeader) {

                    // Debug: dump all section titles
                    const allTitles = [];
                    document.querySelectorAll('.uni-section__content-title, .uni-section-header, .fd-com-box .uni-section-header').forEach(t => {
                        allTitles.push((t.innerText || '').trim().slice(0, 30));
                    });
                    const allText = (document.body.innerText || '').split('\\n').filter(l => l.trim()).slice(0, 20);
                    return { err: 'section not found: ' + sectionName, allSectionTitles: allTitles, pageFirstLines: allText };

                }

                // 找到 section 容器(父元素)：向上查找直到找到包含 fd-sscyr-add-btn 的容器

                let sectionContainer = sectionHeader;

                let addBtns = [];

                for (let i = 0; i < 20; i++) {

                    if (!sectionContainer.parentElement) break;

                    sectionContainer = sectionContainer.parentElement;

                    // 专门查找 fd-sscyr-add-btn 按钮

                    addBtns = sectionContainer.querySelectorAll('.fd-sscyr-add-btn');

                    if (addBtns.length > 0) break;

                }

                // 在 section 容器内查找 fd-sscyr-add-btn 按钮

                if (addBtns.length > 0) {

                    for (const btn of addBtns) {

                        const text = (btn.innerText || '').trim();

                        if (text.includes(buttonText) && isVisible(btn)) {

                            btn.scrollIntoView({ behavior: 'instant', block: 'center' });

                            btn.click();

                            return { ok: true, section: sectionName, button: buttonText, method: 'js-section-add-btn', container: sectionContainer.tagName };

                        }

                    }

                }

                // 如果 fd-sscyr-add-btn 没找到，尝试通用按钮查找

                const buttons = Array.from(sectionContainer.querySelectorAll('button, uni-button, .btn, [class*="btn"], [class*="button"]'));

                for (const btn of buttons) {

                    const text = (btn.innerText || '').trim();

                    if (text.includes(buttonText) && isVisible(btn)) {

                        btn.scrollIntoView({ behavior: 'instant', block: 'center' });

                        btn.click();

                        return { ok: true, section: sectionName, button: buttonText, method: 'js-section-generic', container: sectionContainer.tagName };

                    }

                }

                // 如果找不到，在整个页面查找按钮

                const allButtons = Array.from(document.querySelectorAll('button, uni-button, .btn, [class*="btn"], [class*="button"]'));

                for (const btn of allButtons) {

                    const text = (btn.innerText || '').trim();

                    if (text.includes(buttonText) && isVisible(btn)) {

                        btn.scrollIntoView({ behavior: 'instant', block: 'center' });

                        btn.click();

                        return { ok: true, button: buttonText, method: 'js-global' };

                    }

                }

                return { err: 'button not found: ' + buttonText };

            }""", {"sectionName": section_name, "buttonText": button_text})

            if result.get('ok'):

                page.wait_for_timeout(1000)

                return result

            else:

                return {'err': result.get('err', 'button not found')}

        except Exception as e:

            return {'err': f'点击按钮失败: {e}'}

    def _ensure_party_card_editable(self, page, section_name: str) -> dict:

            """确保当事人卡片可编辑"""

            try:

                # 查找编辑按钮

                edit_btn = page.locator(f'text=编辑, button:has-text("编辑")').first

                if edit_btn.count() > 0 and edit_btn.is_visible(timeout=2000):

                    edit_btn.click(timeout=5000)

                    page.wait_for_timeout(1000)

                    return {'ok': True, 'action': 'clicked_edit'}

                # 检查是否有输入框可见

                inputs = page.locator('input:visible, textarea:visible').count()

                if inputs > 0:

                    return {'ok': True, 'action': 'already_editable', 'inputs': inputs}

                return {'ok': True, 'action': 'no_action_needed'}

            except Exception as e:

                return {'err': f'确保可编辑失败: {e}'}

    def _vue_click_save(self, page) -> dict:

        """保存当事人卡片：先深度修复 Vue 数据 null 列表，再调用 submit；失败则返回 err 走 DOM 点击"""

        try:

            result = page.evaluate("""() => {

                function tagOf(v){ return v && v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name); }

                function findAll(v, names, out) {

                    out = out || [];

                    if (!v) return out;

                    const t = tagOf(v);

                    if (t && names.includes(t)) out.push(v);

                    for (const c of v.$children || []) findAll(c, names, out);

                    return out;

                }

                const rootEl = document.querySelector('uni-app');

                if (!rootEl || !rootEl.__vue__) return {err: 'no root vue'};

                const root = rootEl.__vue__;
                console.log('Root element:', rootEl.tagName);
                console.log('Root keys:', Object.keys(root).slice(0, 20));
                console.log('Root children:', root.$children ? root.$children.length : 0);

                const comps = findAll(root, ['ryxx','Ryxx','sscyr','fd-sscyr','Sscyr','party-form','PartyForm']);
                console.log('Found party components:', comps.length);
                for (let i = 0; i < comps.length; i++) {
                    const comp = comps[i];
                    const tag = comp.$options && (comp.$options.name || comp.$options._componentTag);
                    const dataKeys = comp.$data ? Object.keys(comp.$data).slice(0, 20) : [];
                    console.log('Component', i, ':', tag, 'keys:', dataKeys);
                    // Check for ssdlrList
                    if (comp.$data && 'ssdlrList' in comp.$data) {
                        console.log('Found ssdlrList in $data:', comp.$data.ssdlrList);
                    }
                    if ('ssdlrList' in comp) {
                        console.log('Found ssdlrList in comp:', comp.ssdlrList);
                    }
                }

                if (!comps.length) return {err: 'no party component'};

                const ryxx = comps[0];

                const fixed = [];

                // Fix known null list fields FIRST (before deepFix) - recursive search

                function fixNullLists(obj, path, depth) {

                    if (!obj || typeof obj !== 'object' || depth > 5) return;

                    let keys;

                    try { keys = Object.keys(obj); } catch(e){ return; }

                    for (const k of keys) {

                        if (k.charAt(0) === '_' || k === '$') continue;

                        let v;

                        try { v = obj[k]; } catch(e){ continue; }

                        if (typeof v === 'function') continue;

                        // Fix null list fields

                        if (v === null && /(ssdlr|List|list|dlr|dler|agent|yg|bg|dsr)/i.test(k)) {

                            try { obj[k] = []; fixed.push((path || 'obj') + '.' + k); } catch(e){}

                            continue;

                        }

                        // Recurse into plain objects (not Vue components or DOM)

                        if (v && typeof v === 'object' && !v.$options && !v.nodeType && depth < 4) {

                            fixNullLists(v, (path || 'obj') + '.' + k, depth + 1);

                        }

                    }

                }

                fixNullLists(ryxx, 'ryxx', 0);

                if (ryxx.$data) fixNullLists(ryxx.$data, 'ryxx.$data', 0);

                // Explicit ssdlrList fix - this is the most common null pointer

                try {

                    if (!ryxx.ssdlrList) { ryxx.ssdlrList = []; fixed.push('ryxx.ssdlrList'); }

                    if (ryxx.$data && !ryxx.$data.ssdlrList) { ryxx.$data.ssdlrList = []; fixed.push('$data.ssdlrList'); }

                } catch(e) {}

                // Deep-fix: recursively null -> [] for keys that look like lists, on component and nested data objects

                const LIST_KEY = /(list|List|ssdlr|dlr|dler|agent|ry|yg|bg|dsr)$/i;

                function deepFix(obj, depth, path) {

                    if (!obj || typeof obj !== 'object' || depth > 4) return;

                    let keys;

                    try { keys = Object.keys(obj); } catch(e){ return; }

                    for (const k of keys) {

                        // skip vue internals / dom / functions

                        if (k.charAt(0) === '_' || k === '$' ) continue;

                        let v;

                        try { v = obj[k]; } catch(e){ continue; }

                        if (typeof v === 'function') continue;

                        if (v === null && LIST_KEY.test(k)) {

                            try { obj[k] = []; fixed.push(path + '.' + k); } catch(e){}

                            continue;

                        }

                        if (v && typeof v === 'object' && depth < 3) {

                            // only recurse into plain-ish objects / arrays items, not Vue components (have $options)

                            if (!v.$options && !v.nodeType) deepFix(v, depth + 1, path + '.' + k);

                        }

                    }

                }

                deepFix(ryxx, 0, 'ryxx');

                if (ryxx.$data) deepFix(ryxx.$data, 0, '$data');

                // Ensure formEdit/showForm

                if ('formEdit' in ryxx) ryxx.formEdit = true;

                if (ryxx.$data && 'formEdit' in ryxx.$data) ryxx.$data.formEdit = true;

                // call submit inside try

                const methods = ['submit','save','doSave','confirm','handleSave','handleSubmit'];

                // Aggressive null fix for ssdlrList and other critical lists
                try {
                    if (!ryxx.ssdlrList) { ryxx.ssdlrList = []; fixed.push('pre-submit: ryxx.ssdlrList'); }
                    if (ryxx.$data && !ryxx.$data.ssdlrList) { ryxx.$data.ssdlrList = []; fixed.push('pre-submit: $data.ssdlrList'); }
                    if (ryxx.dlrs && !Array.isArray(ryxx.dlrs)) { ryxx.dlrs = []; fixed.push('pre-submit: ryxx.dlrs'); }
                    if (ryxx.$data && ryxx.$data.dlrs && !Array.isArray(ryxx.$data.dlrs)) { ryxx.$data.dlrs = []; fixed.push('pre-submit: $data.dlrs'); }
                    // Also check for nested null in ssdlrList items
                    if (Array.isArray(ryxx.ssdlrList)) {
                        for (let i = 0; i < ryxx.ssdlrList.length; i++) {
                            if (!ryxx.ssdlrList[i]) { ryxx.ssdlrList[i] = {}; fixed.push('pre-submit: ssdlrList[' + i + ']'); }
                        }
                    }
                } catch(e) { fixed.push('pre-submit error: ' + e.message); }

                for (const m of methods) {

                    if (typeof ryxx[m] === 'function') {

                        try {

                            const dataKeys = Object.keys(ryxx.$data || {}).slice(0, 30);
                            const ygList = ryxx.$data && ryxx.$data.ygList ? JSON.stringify(ryxx.$data.ygList).substring(0, 500) : 'none';
                            const bgList = ryxx.$data && ryxx.$data.bgList ? JSON.stringify(ryxx.$data.bgList).substring(0, 500) : 'none';
                            const ssdlrList = ryxx.$data && ryxx.$data.ssdlrList ? JSON.stringify(ryxx.$data.ssdlrList).substring(0, 500) : 'none';
                            console.log('Save data keys:', dataKeys);
                            console.log('ygList:', ygList);
                            console.log('bgList:', bgList);
                            console.log('ssdlrList:', ssdlrList);
                            // Debug: check ssdlrList before submit
                            const hasSsdlr = 'ssdlrList' in ryxx;
                            const ssdlrVal = ryxx.ssdlrList;
                            const hasDataSsdlr = ryxx.$data && 'ssdlrList' in ryxx.$data;
                            const dataSsdlrVal = ryxx.$data ? ryxx.$data.ssdlrList : undefined;
                            console.log('Before submit: hasSsdlr=', hasSsdlr, 'val=', ssdlrVal, 'hasDataSsdlr=', hasDataSsdlr, 'dataVal=', dataSsdlrVal);

                            // Recursive find and fix ssdlrList
                            function findAndFixSsdlr(obj, path, depth) {
                                if (!obj || typeof obj !== 'object' || depth > 5) return;
                                if (Array.isArray(obj)) {
                                    for (let i = 0; i < obj.length; i++) {
                                        findAndFixSsdlr(obj[i], path + '[' + i + ']', depth + 1);
                                    }
                                    return;
                                }
                                for (const k of Object.keys(obj)) {
                                    if (k === 'ssdlrList' && obj[k] === null) {
                                        obj[k] = [];
                                        fixed.push('found-fix: ' + path + '.ssdlrList');
                                    }
                                    if (typeof obj[k] === 'object' && obj[k] !== null) {
                                        findAndFixSsdlr(obj[k], path + '.' + k, depth + 1);
                                    }
                                }
                            }
                            findAndFixSsdlr(ryxx, 'ryxx', 0);
                            if (ryxx.$data) findAndFixSsdlr(ryxx.$data, '$data', 0);

                            // Debug: list all properties of ryxx
                            const allProps = [];
                            for (const k of Object.keys(ryxx)) {
                                if (!k.startsWith('_') && !k.startsWith('$')) {
                                    const v = ryxx[k];
                                    const type = Array.isArray(v) ? 'array' : typeof v;
                                    allProps.push(k + ':' + type);
                                }
                            }
                            console.log('ryxx props:', allProps.slice(0, 50).join(', '));

                            // Also check $data
                            if (ryxx.$data) {
                                const dataProps = [];
                                for (const k of Object.keys(ryxx.$data)) {
                                    const v = ryxx.$data[k];
                                    const type = Array.isArray(v) ? 'array' : typeof v;
                                    dataProps.push(k + ':' + type);
                                }
                                console.log('$data props:', dataProps.slice(0, 50).join(', '));
                            }

                            return {
                                debug: true,
                                ryxxKeys: Object.keys(ryxx).filter(k => !k.startsWith('_') && !k.startsWith('$')).slice(0, 50),
                                dataKeys: ryxx.$data ? Object.keys(ryxx.$data).slice(0, 50) : [],
                                hasSsdlr: 'ssdlrList' in ryxx,
                                ssdlrVal: ryxx.ssdlrList,
                                hasDataSsdlr: ryxx.$data && 'ssdlrList' in ryxx.$data,
                                dataSsdlrVal: ryxx.$data ? ryxx.$data.ssdlrList : undefined,
                                method: m
                            };

                            if (r && typeof r.then === 'function') {

                                return {ok: true, method: m, async: true, fixed: fixed.slice(0,20)};

                            }

                            return {ok: true, method: m, fixed: fixed.slice(0,20)};

                        } catch (e) {

                            return {err: 'submit threw: ' + e.message, method: m, fixed: fixed.slice(0,20)};

                        }

                    }

                }

                return {err: 'no submit method', fixed: fixed.slice(0,20)};

            }""")

            return result

        except Exception as e:

            return {'err': f'vue save failed: {e}'}

    def _click_card_save(self, page, party: dict = None) -> dict:

        """点击卡片保存按钮"""

        # 保存前再次校正自然人派生字段：填写后站点 watcher 可能把 csrq 等值覆盖进 nl，
        # 导致 "年龄不能超过3个字符" 校验失败；此处保证 nl 为 1-3 位数字字符串。

        if party and party.get("__role") not in (None, "代理人") and party.get("litigant_type", "自然人") == "自然人":

            try:

                pre_fix = self._ensure_party_derived_fields(page, party, party.get("__role", "当事人"))

                logger.info(f"保存前派生字段校正({party.get('__role')}): {pre_fix}")

            except Exception as e:

                logger.debug(f"保存前派生字段校正失败: {e}")

        try:

            # 先尝试 Vue 方法保存(最可靠)

            try:

                vue_save = self._vue_click_save(page)

                logger.info(f"Vue save result: {vue_save}")

                if vue_save.get('ok'):
                    # Verify Vue save actually persisted data to role lists
                    page.wait_for_timeout(2000)
                    verify_persist = page.evaluate("""() => {
                        function tagOf(v){ return v && v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name); }
                        function findAll(v, names, out){ out=out||[]; if(!v) return out; const t=tagOf(v); if(t&&names.includes(t)) out.push(v); for(const c of v.$children||[]) findAll(c,names,out); return out; }
                        const rootEl = document.querySelector('uni-app');
                        if (!rootEl || !rootEl.__vue__) return {err: 'no root vue'};
                        const comps = findAll(rootEl.__vue__, ['ryxx','Ryxx','sscyr','fd-sscyr']);
                        if (!comps.length) return {err: 'no ryxx'};
                        const ryxx = comps[0];
                        const lists = {};
                        let totalParties = 0;
                        for (const key of ['ygList', 'bgList', 'dsrList', 'dlrList']) {
                            const list = ryxx[key] || (ryxx.$data && ryxx.$data[key]) || [];
                            lists[key] = list.length;
                            totalParties += list.length;
                        }
                        const formOpen = ryxx.showForm && (ryxx.showForm.yg || ryxx.showForm.bg || ryxx.showForm.dsr || ryxx.showForm.dlr);
                        return {lists, totalParties, formOpen: !!formOpen, hasData: totalParties > 0};
                    }""")
                    logger.info(f"Vue save verification: {verify_persist}")
                    if verify_persist.get('hasData') and not verify_persist.get('formOpen'):
                        logger.info("Vue save succeeded - data persisted to lists")
                        return {'ok': True, 'method': 'vue-save', 'detail': vue_save, 'verify': verify_persist}
                    else:
                        logger.warning(f"Vue save returned ok but data not persisted (hasData={verify_persist.get('hasData')}, formOpen={verify_persist.get('formOpen')}), trying fallback...")
            except Exception as e:
                logger.debug(f"Vue save failed: {e}")
            except Exception as e:

                logger.debug(f"Vue save failed: {e}")

            # Try smart save (real UI click) FIRST before direct-vue-data

            # direct-vue-data only modifies Vue data without triggering real form validation/submission

            logger.debug("Trying smart save (real UI click) before direct-vue-data...")

            smart_result_early = page.evaluate("""() => {

                function isVisible(el) {

                    if (!el) return false;

                    const r = el.getBoundingClientRect();

                    return r.width > 0 && r.height > 0;

                }

                const allButtons = Array.from(document.querySelectorAll('uni-button, button, [class*="btn"]'));

                const saveButtons = allButtons.filter(btn => {

                    const text = (btn.innerText || '').trim();

                    return text === '保存' && isVisible(btn);

                });

                if (saveButtons.length === 0) {

                    const allTexts = allButtons.filter(isVisible).map(b => (b.innerText || '').trim()).filter(t => t).slice(0, 30);

                    return {err: 'no save button found', visibleButtons: allTexts};

                }

                // Find the save button closest to a visible input (the active form)

                const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea')).filter(isVisible);

                for (const input of inputs) {

                    let container = input;

                    for (let i = 0; i < 20; i++) {

                        if (!container.parentElement) break;

                        container = container.parentElement;

                        const btn = Array.from(container.querySelectorAll('uni-button, button')).find(b => {

                            const text = (b.innerText || '').trim();

                            return text === '保存' && isVisible(b);

                        });

                        if (btn) {

                            btn.scrollIntoView({behavior: 'instant', block: 'center'});

                            btn.click();

                            return {ok: true, method: 'smart-early-near-input', totalSaveBtns: saveButtons.length};

                        }

                    }

                }

                // Fallback: click the last visible save button

                const btnToClick = saveButtons[saveButtons.length - 1];

                btnToClick.scrollIntoView({behavior: 'instant', block: 'center'});

                btnToClick.click();

                return {ok: true, method: 'smart-early-last', totalSaveBtns: saveButtons.length};

            }""")

            if not smart_result_early.get('ok'):

                logger.warning(f"Smart save 未能点击保存按钮: {smart_result_early}")

            if smart_result_early.get('ok'):

                page.wait_for_timeout(2000)

                logger.info(f"Smart save (early): {smart_result_early}")

                # 捕获保存后的页面提示（toast / 表单校验错误），便于诊断验证失败原因

                save_hints = []

                try:

                    save_hints = page.evaluate("""() => {

                        function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

                        const hints = [];

                        const sels = ['.uni-forms-item__error', '[class*="toast"]', '[class*="Toast"]', '.uni-modal__bd', '[class*="error"]', '[class*="message"]'];

                        for (const sel of sels) {

                            for (const el of Array.from(document.querySelectorAll(sel))) {

                                if (!isVisible(el)) continue;

                                const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();

                                if (t && t.length < 120 && !hints.some(h => h.text === t)) hints.push({sel, text: t});

                            }

                        }

                        return hints.slice(0, 8);

                    }""")

                    if save_hints:

                        logger.info(f"保存后页面提示: {save_hints}")

                except Exception as _e:

                    logger.debug(f"保存后提示捕获失败: {_e}")

                # Verify the save actually worked by checking if form closed

                form_closed = page.evaluate("""() => {

                    function tagOf(v){ return v && v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name); }

                    function findAll(v, names, out){ out=out||[]; if(!v) return out; const t=tagOf(v); if(t&&names.includes(t)) out.push(v); for(const c of v.$children||[]) findAll(c,names,out); return out; }

                    const rootEl = document.querySelector('uni-app');

                    if (!rootEl || !rootEl.__vue__) return {err: 'no root vue'};

                    const comps = findAll(rootEl.__vue__, ['ryxx','Ryxx','sscyr','fd-sscyr']);

                    if (!comps.length) return {err: 'no ryxx'};

                    const ryxx = comps[0];

                    const anyFormOpen = ryxx.showForm && (ryxx.showForm.yg || ryxx.showForm.bg || ryxx.showForm.dsr || ryxx.showForm.dlr);

                    return {formOpen: anyFormOpen, showForm: ryxx.showForm};

                }""")

                logger.debug(f"Form state after smart save: {form_closed}")

                if not form_closed.get('formOpen', True):

                    # Form closed, but we need to verify data actually persisted to the list

                    # Wait a bit for Vue to propagate data

                    page.wait_for_timeout(1500)

                    # Check if party data is actually in the role list

                    verify_save = page.evaluate("""() => {

                        function tagOf(v){ return v && v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name); }

                        function findAll(v, names, out){ out=out||[]; if(!v) return out; const t=tagOf(v); if(t&&names.includes(t)) out.push(v); for(const c of v.$children||[]) findAll(c,names,out); return out; }

                        const rootEl = document.querySelector('uni-app');

                        if (!rootEl || !rootEl.__vue__) return {err: 'no root vue'};

                        const comps = findAll(rootEl.__vue__, ['ryxx','Ryxx','sscyr','fd-sscyr']);

                        if (!comps.length) return {err: 'no ryxx'};

                        const ryxx = comps[0];

                        // Check all role lists

                        const lists = {};

                        let totalParties = 0;

                        for (const key of ['ygList', 'bgList', 'dsrList', 'dlrList']) {

                            const list = ryxx[key] || (ryxx.$data && ryxx.$data[key]) || [];

                            lists[key] = list.length;

                            totalParties += list.length;

                        }

                        return {lists, totalParties, hasData: totalParties > 0};

                    }""")

                    logger.info(f"Post-save verification: {verify_save}")

                    if verify_save.get('hasData'):

                        logger.info("Smart save succeeded - form closed and data persisted")

                        return {'ok': True, 'method': 'smart-save-early', 'detail': smart_result_early, 'formClosed': form_closed, 'verify': verify_save}

                    else:

                        logger.warning("Smart save closed form but NO data in lists, falling back to direct-vue-data")

                        # Don't return here, let it fall through to direct-vue-data

                else:

                    validation_hints = [
                        h for h in (save_hints or [])
                        if isinstance(h, dict) and (
                            h.get('sel') == '.uni-forms-item__error'
                            or '不能为空' in h.get('text', '')
                            or '格式' in h.get('text', '')
                            or '请输入有效' in h.get('text', '')
                            or '不正确' in h.get('text', '')
                            or '无效' in h.get('text', '')
                        )
                    ]

                    if validation_hints:

                        logger.warning(f"Smart save 触发表单校验错误，停止直接注入兜底: {validation_hints}")

                        return {
                            'ok': False,
                            'err': 'form validation failed',
                            'validation_errors': validation_hints,
                            'detail': smart_result_early,
                            'formState': form_closed,
                        }

                    logger.warning("Smart save clicked but form still open, trying direct-vue-data fallback")

            # If smart save failed or form still open, try direct data manipulation as last resort

            # This bypasses the submit method that has the null pointer issue

            # Support all roles: yg(原告), bg(被告), dsr(第三人), dlr(代理人)

            direct_save = page.evaluate(r"""(partyData) => {
                const PARTY_DATA = partyData || {};

                function tagOf(v){ return v && v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name); }

                function findAll(v, names, out){ out=out||[]; if(!v) return out; const t=tagOf(v); if(t&&names.includes(t)) out.push(v); for(const c of v.$children||[]) findAll(c,names,out); return out; }

                const rootEl = document.querySelector('uni-app');

                if (!rootEl || !rootEl.__vue__) return {err:'no root vue'};

                const comps = findAll(rootEl.__vue__, ['ryxx','Ryxx','sscyr','fd-sscyr']);

                if (!comps.length) return {err:'no ryxx'};

                const ryxx = comps[0];

                // Determine which form is currently open

                let roleKey = 'bg'; // default
                if (ryxx.showForm) {
                    if (ryxx.showForm.yg) roleKey = 'yg';
                    else if (ryxx.showForm.bg) roleKey = 'bg';
                    else if (ryxx.showForm.dsr) roleKey = 'dsr';
                    else if (ryxx.showForm.dlr) roleKey = 'dlr';
                }
                // If form closed but PARTY_DATA has role hint, use it
                if (roleKey === 'bg' && !(ryxx.showForm && ryxx.showForm.bg) && PARTY_DATA && PARTY_DATA.__role) {
                    const roleMap = {'原告': 'yg', '被告': 'bg', '第三人': 'dsr', '代理人': 'dlr'};
                    if (roleMap[PARTY_DATA.__role]) roleKey = roleMap[PARTY_DATA.__role];
                }

                const roleNameMap = {'yg':'原告','bg':'被告','dsr':'第三人','dlr':'代理人'};

                const roleName = roleNameMap[roleKey] || '当事人';

                // Try to read from form data first - check role-specific form

                let party = {};

                const form = ryxx[roleKey+'Form'] || ryxx.form || ryxx.formData;

                if (form) {

                    for (const k of Object.keys(form)) {

                        if (form[k] !== null && form[k] !== undefined && form[k] !== '') {

                            party[k] = form[k];

                        }

                    }

                }

                // If no name in form data, read from DOM inputs

                if (!party.name && !party.xm) {

                    function isVisible(el) { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

                    const containers = ['uni-forms-item', '.uni-forms-item', '.fd-com-form-item', '[class*="form-item"]', '[class*="formItem"]', '.uni-form-item', '.form-item', 'uni-view[class*="item"]'];

                    const labelMap = {

                        '姓名': 'name', '名称': 'name', '证件号码': 'certNo', '联系电话': 'phone',

                        '住所地(户籍所在地)': 'address', '经常居住地': 'usualAddress',

                        '工作单位': 'workUnit', '性别': 'gender', '民族': 'nation',

                        '证件类型': 'certType', '国别或地区': 'country', '职务': 'position',

                        '统一社会信用代码': 'certNo', '法定代表人/负责人': 'legalPerson',

                        '被代理人': 'representedParty', '代理人类型': 'agentType',

                        '代理人证件号码': 'certNo', '单位': 'workUnit'

                    };

                    for (const sel of containers) {

                        const items = Array.from(document.querySelectorAll(sel)).filter(isVisible);

                        for (const item of items) {

                            const labelEl = item.querySelector('.uni-forms-item__label, .uni-forms-item__title, .fd-form-label, .label, [class*="label"]');

                            if (!labelEl) continue;

                            const labelText = (labelEl.innerText || '').replace(/\s+/g, ' ').trim();

                            const input = item.querySelector('input, textarea');

                            if (!input) continue;

                            const value = input.value;

                            if (!value) continue;

                            // Map label to field name

                            for (const [label, field] of Object.entries(labelMap)) {

                                if (labelText.includes(label)) {

                                    party[field] = value;

                                    break;

                                }

                            }

                        }

                    }

                }

                // Ensure required fields

                if (!party.name && !party.xm) {

                    // Last resort: read any visible input with a value

                    const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"])')).filter(el => {

                        const r = el.getBoundingClientRect();

                        return r.width > 0 && r.height > 0 && el.value;

                    });

                    for (const inp of inputs) {

                        const ph = inp.placeholder || '';

                        if (ph.includes('姓名') || (ph.includes('请输入') && !ph.includes('电话') && !ph.includes('手机') && !ph.includes('联系'))) {

                            party.name = inp.value;

                            break;

                        }

                    }

                }

                // Fallback: use passed party data if DOM read failed
                if (!party.name && !party.xm && PARTY_DATA) {
                    for (const k of Object.keys(PARTY_DATA)) {
                        if (PARTY_DATA[k] !== null && PARTY_DATA[k] !== undefined && PARTY_DATA[k] !== '') {
                            party[k] = PARTY_DATA[k];
                        }
                    }
                }
                if (!party.name && !party.xm) return {err: 'no name found', formKeys: form ? Object.keys(form).slice(0,10) : 'no form', partyKeys: Object.keys(party)};

                // Add to role-specific list

                const listKey = roleKey + 'List';

                if (!ryxx[listKey]) ryxx[listKey] = [];

                if (ryxx.$data && !ryxx.$data[listKey]) ryxx.$data[listKey] = [];

                // Check if already exists

                const name = party.name || party.xm;

                const exists = ryxx[listKey].some(p => (p.name || p.xm) === name);

                if (!exists) {

                    ryxx[listKey].push({...party});

                    if (ryxx.$data[listKey]) ryxx.$data[listKey].push({...party});

                    // CRITICAL: sync dsrList + wsla lists + detail for preview rendering
                    try {
                        const roleToDsr = {yg: '原告', bg: '被告', dsr: '第三人', dlr: '代理人'};
                        const dsrEntry = Object.assign({}, party, {
                            dsrType: party.dsrType || roleToDsr[roleKey] || '当事人'
                        });
                        if (dsrEntry.name && !dsrEntry.xm) dsrEntry.xm = dsrEntry.name;
                        if (dsrEntry.idcard && !dsrEntry.zjhm) dsrEntry.zjhm = dsrEntry.idcard;
                        if (dsrEntry.phone && !dsrEntry.mobile) dsrEntry.mobile = dsrEntry.phone;
                        // Sync dsrList
                        if (!ryxx.dsrList) ryxx.dsrList = [];
                        if (ryxx.$data && !ryxx.$data.dsrList) ryxx.$data.dsrList = [];
                        const dsrList = ryxx.$data ? ryxx.$data.dsrList : ryxx.dsrList;
                        if (!dsrList.some(x => (x.name || x.xm) === (dsrEntry.name || dsrEntry.xm))) {
                            dsrList.push(dsrEntry);
                        }
                        // Sync wsla component
                        const rootElW = document.querySelector('uni-app');
                        if (rootElW && rootElW.__vue__) {
                            function tagOfW(v){ return v && v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name); }
                            function findAllW(v, names, out){ out=out||[]; if(!v) return out; const t=tagOfW(v); if(t&&names.includes(t)) out.push(v); for(const c of v.$children||[]) findAllW(c,names,out); return out; }
                            const wsla = findAllW(rootElW.__vue__, ['pagesWsla-common-wsla-index'])[0];
                            if (wsla) {
                                if (!wsla.ygList) wsla.ygList = [];
                                if (!wsla.bgList) wsla.bgList = [];
                                if (!wsla.dlrList) wsla.dlrList = [];
                                if (!wsla.dsrList) wsla.dsrList = [];
                                const t = dsrEntry.dsrType || '';
                                if (t.includes('原告') && !wsla.ygList.some(x => (x.name || x.xm) === (dsrEntry.name || dsrEntry.xm))) wsla.ygList.push(dsrEntry);
                                if (t.includes('被告') && !wsla.bgList.some(x => (x.name || x.xm) === (dsrEntry.name || dsrEntry.xm))) wsla.bgList.push(dsrEntry);
                                if (t.includes('代理') && !wsla.dlrList.some(x => (x.name || x.xm) === (dsrEntry.name || dsrEntry.xm))) wsla.dlrList.push(dsrEntry);
                                if (!wsla.dsrList.some(x => (x.name || x.xm) === (dsrEntry.name || dsrEntry.xm))) wsla.dsrList.push(dsrEntry);
                                if (wsla.$forceUpdate) wsla.$forceUpdate();
                            }
                            // CRITICAL: sync detail component
                            const detailComps = findAllW(rootElW.__vue__, ['detail']);
                            for (const detail of detailComps) {
                                if (!detail.detail) detail.detail = {};
                                const dd = detail.detail;
                                if (!dd.list || Array.isArray(dd.list)) dd.list = {};
                                if (!dd.dsrs) dd.dsrs = [];
                                if (!dd.dlrs) dd.dlrs = [];
                                const t = dsrEntry.dsrType || '';
                                const typeKey = t.includes('原告') ? '原告' : (t.includes('被告') ? '被告' : (t.includes('代理') ? '代理人' : t));
                                if (!dd.list[typeKey]) dd.list[typeKey] = [];
                                if (!dd.list[typeKey].some(x => (x.name || x.xm) === (dsrEntry.name || dsrEntry.xm))) dd.list[typeKey].push(dsrEntry);
                                if (!dd.dsrs.some(x => (x.name || x.xm) === (dsrEntry.name || dsrEntry.xm))) dd.dsrs.push(dsrEntry);
                                if (t.includes('代理') && !dd.dlrs.some(x => (x.name || x.xm) === (dsrEntry.name || dsrEntry.xm))) dd.dlrs.push(dsrEntry);
                                // Sync detail.list (data)
                                const dData = detail.$data || detail;
                                if (detail.$set) {
                                    detail.$set(dData, 'list', dd.list);
                                    detail.$set(dData, 'dsrs', dd.dsrs);
                                    detail.$set(dData, 'dlrs', dd.dlrs);
                                } else {
                                    dData.list = dd.list;
                                    dData.dsrs = dd.dsrs;
                                    dData.dlrs = dd.dlrs;
                                }
                                detail.list = dd.list;
                                detail.dsrs = dd.dsrs;
                                detail.dlrs = dd.dlrs;
                                if (detail.$forceUpdate) detail.$forceUpdate();
                            }
                        }
                    } catch(e) { console.error('sync detail failed:', e); }

                }

                // Ensure ssdlrList exists to prevent null pointer in Vue submit

                try {

                    if (!ryxx.ssdlrList) ryxx.ssdlrList = [];

                    if (ryxx.$data && !ryxx.$data.ssdlrList) ryxx.$data.ssdlrList = [];

                } catch(e) {}

                // Close the form

                if (ryxx.showForm) {

                    ryxx.showForm.bg = false;

                    ryxx.showForm.yg = false;

                    ryxx.showForm.dsr = false;

                    ryxx.showForm.dlr = false;

                }

                if (ryxx.formEdit !== undefined) ryxx.formEdit = false;

                // Force update

                if (ryxx.$forceUpdate) ryxx.$forceUpdate();

                return {ok: true, method: 'direct-vue-data', role: roleName, partyName: name, listKey: listKey, listLength: ryxx[listKey].length};

            }""", party)

            logger.debug(f"Direct save attempt result: {direct_save}")

            if direct_save.get('ok'):

                page.wait_for_timeout(1000)

                logger.info(f"Direct Vue data save: {direct_save}")

                return {'ok': True, 'method': 'direct-vue-data', 'detail': direct_save}

            # 智能查找：找到包含可见输入框的最近容器，然后点击其中的保存按钮

            # 优先查找 footer/btn-container 中的保存按钮

            smart_result = page.evaluate("""() => {

                function isVisible(el) { 

                    if (!el) return false; 

                    const r = el.getBoundingClientRect(); 

                    return r.width > 0 && r.height > 0; 

                }

                // Strategy 1: Find all visible save buttons, click the one in the active form

                // Look for buttons with exact text '保存'

                const allButtons = Array.from(document.querySelectorAll('uni-button, button, [class*="btn"], uni-view, view, span, div'));

                const saveButtons = allButtons.filter(btn => {

                    const text = (btn.innerText || '').trim();

                    return text === '保存' && isVisible(btn);

                });

                if (saveButtons.length === 0) return {err: 'no save button found'};

                // If multiple save buttons, find the one closest to a visible input

                if (saveButtons.length > 1) {

                    // Find the save button that is in the same container as a visible input

                    const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea')).filter(isVisible);

                    for (const input of inputs) {

                        let container = input;

                        for (let i = 0; i < 20; i++) {

                            if (!container.parentElement) break;

                            container = container.parentElement;

                            const btn = Array.from(container.querySelectorAll('uni-button, button, [class*="btn"]')).find(b => {

                                const text = (b.innerText || '').trim();

                                return text === '保存' && isVisible(b);

                            });

                            if (btn) {

                                btn.scrollIntoView({behavior: 'instant', block: 'center'});

                                btn.click();

                                return {ok: true, method: 'smart-container-near-input', inputLabel: input.placeholder || input.name || '', totalSaveBtns: saveButtons.length};

                            }

                        }

                    }

                }

                // Single save button or fallback: click the first/last visible one

                // Usually the last one is in the currently open form

                const btnToClick = saveButtons[saveButtons.length - 1];

                btnToClick.scrollIntoView({behavior: 'instant', block: 'center'});

                btnToClick.click();

                return {ok: true, method: 'smart-container-last', totalSaveBtns: saveButtons.length};

            }""")

            if smart_result.get('ok'):

                page.wait_for_timeout(1500)

                logger.info(f"智能保存: {smart_result}")

                return {'ok': True, 'method': 'smart-save', 'detail': smart_result}

            # 先滚动到页面底部，确保保存按钮可见

            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            page.wait_for_timeout(500)

            save_selectors = [

                # Most specific first: exact save button text

                'uni-button:has-text("保存")',

                'button:has-text("保存")',

                '.uni-btn:has-text("保存")',

                '.uni-button:has-text("保存")',

                'button[type="button"]:has-text("保存")',

                '.fd-btn:has-text("保存")',

                '.btn-save',

                '[type="primary"]:has-text("保存")',

                '[class*="save"]',

                # Then try other save-like buttons

                'button:has-text("确定")',

                'uni-button:has-text("确定")',

                'button:has-text("提交")',

                'uni-button:has-text("提交")',

                # Last resort: text matching

                'text=保存',

                'text=确定',

            ]

            for selector in save_selectors:

                try:

                    btn = page.locator(selector).first

                    if btn.count() > 0 and btn.is_visible(timeout=2000):

                        btn.scroll_into_view_if_needed(timeout=3000)

                        page.wait_for_timeout(500)

                        btn.click(timeout=5000)

                        page.wait_for_timeout(1500)

                        return {'ok': True, 'selector': selector}

                except:

                    continue

            # Special handling for fd-com-btn-container with '取消\n保存'

            try:

                containers = page.locator('.fd-com-btn-container, [class*="btn-container"]').all()

                for container in containers:

                    if container.is_visible(timeout=1000):

                        # Look for save button inside container

                        save_btn = container.locator('uni-button:has-text("保存"), button:has-text("保存")').first

                        if save_btn.count() > 0 and save_btn.is_visible(timeout=1000):

                            save_btn.scroll_into_view_if_needed(timeout=3000)

                            page.wait_for_timeout(500)

                            save_btn.click(timeout=5000)

                            page.wait_for_timeout(1500)

                            return {'ok': True, 'selector': 'container-save-btn'}

            except Exception as e:

                logger.debug(f"Container save failed: {e}")

            # Special handling for fd-com-btn-container with '取消\n保存'

            try:

                result = page.evaluate("""() => {

                    function isVisible(el) { 

                        if (!el) return false; 

                        const r = el.getBoundingClientRect(); 

                        return r.width > 0 && r.height > 0; 

                    }

                    // Find fd-com-btn-container

                    const containers = document.querySelectorAll('.fd-com-btn-container, [class*="btn-container"]');

                    for (const container of containers) {

                        if (!isVisible(container)) continue;

                        // Find all buttons inside

                        const btns = container.querySelectorAll('uni-button, button, [class*="btn"]');

                        for (const btn of btns) {

                            const text = (btn.innerText || '').trim();

                            if (text === '保存') {

                                btn.scrollIntoView({behavior: 'instant', block: 'center'});

                                btn.click();

                                return {ok: true, text: text, tag: btn.tagName, source: 'container-js'};

                            }

                        }

                        // If no exact match, look for any element with '保存' text

                        const allEls = container.querySelectorAll('*');

                        for (const el of allEls) {

                            const text = (el.innerText || '').trim();

                            if (text === '保存' && isVisible(el)) {

                                el.scrollIntoView({behavior: 'instant', block: 'center'});

                                el.click();

                                return {ok: true, text: text, tag: el.tagName, source: 'container-any'};

                            }

                        }

                    }

                    return {err: 'no container save found'};

                }""")

                if result.get('ok'):

                    page.wait_for_timeout(1500)

                    return {'ok': True, 'method': 'container-js', 'detail': result}

            except Exception as e:

                logger.debug(f"Container JS save failed: {e}")

            # 如果找不到，尝试通过文本查找所有包含"保存"的元素

            try:

                # 使用 JavaScript 查找并点击

                result = page.evaluate("""() => {

                    function isVisible(el) { 

                        if (!el) return false; 

                        const r = el.getBoundingClientRect(); 

                        return r.width > 0 && r.height > 0; 

                    }

                    // Strategy 1: Find exact save button by text, avoiding containers with '取消\n保存'

                    const allBtns = Array.from(document.querySelectorAll('uni-button, button, [class*="btn"]')).filter(isVisible);

                    for (const btn of allBtns) {

                        const text = (btn.innerText || '').trim();

                        // Exact match for save button text

                        if (text === '保存') {

                            btn.scrollIntoView({behavior: 'instant', block: 'center'});

                            btn.click();

                            return {ok: true, text: text, tag: btn.tagName, source: 'exact-save'};

                        }

                    }

                    // Strategy 2: Find container with '取消\n保存' and click the save part

                    const containers = document.querySelectorAll('.fd-com-btn-container, [class*="btn-container"], [class*="footer"]');

                    for (const container of containers) {

                        if (!isVisible(container)) continue;

                        const text = (container.innerText || '').trim();

                        if (text.includes('保存')) {

                            // Find the actual save button inside

                            const saveBtn = Array.from(container.querySelectorAll('uni-button, button, [class*="btn"]')).find(b => {

                                return (b.innerText || '').trim() === '保存';

                            });

                            if (saveBtn && isVisible(saveBtn)) {

                                saveBtn.scrollIntoView({behavior: 'instant', block: 'center'});

                                saveBtn.click();

                                return {ok: true, text: '保存', tag: saveBtn.tagName, source: 'container-save'};

                            }

                        }

                    }

                    // Strategy 3: Find by partial text but ensure it's a button element

                    for (const btn of allBtns) {

                        const text = (btn.innerText || '').trim();

                        if (text.includes('保存') && !text.includes('取消') && text.length <= 5) {

                            btn.scrollIntoView({behavior: 'instant', block: 'center'});

                            btn.click();

                            return {ok: true, text: text, tag: btn.tagName, source: 'partial-save'};

                        }

                    }

                    return {err: 'no save button found'};

                }""")

                if result.get('ok'):

                    page.wait_for_timeout(1500)

                    return {'ok': True, 'method': 'js-click', 'detail': result}

            except:

                pass

            # 最后尝试：直接查找页面上所有可点击的文本

            try:

                all_texts = page.locator('text=/保存|确定|提交/').all()

                for btn in all_texts:

                    if btn.is_visible(timeout=1000):

                        btn.click(timeout=5000)

                        page.wait_for_timeout(1500)

                        return {'ok': True, 'selector': 'text-regex'}

            except:

                pass

            return {'err': '未找到保存按钮'}

        except Exception as e:

            return {'err': f'保存失败: {e}'}

    def complete_case_info_and_preview(self, page, case_data: dict) -> dict:

        """完善案件信息并预览"""

        try:

            # 等待页面加载

            page.wait_for_timeout(2000)

            # 尝试点击下一步进入预览/提交页面

            next_result = self._click_page_bottom_next(page)

            if next_result.get('ok'):

                logger.info(f"点击下一步: {next_result}")

                page.wait_for_timeout(2000)

            else:

                logger.info("未找到下一步按钮，可能已在最后一步")

            # 检查是否有预览或确认按钮

            preview_selectors = [

                'button:has-text("预览")',

                'uni-button:has-text("预览")',

                'text=预览',

                'button:has-text("确认")',

                'uni-button:has-text("确认")',

                'button:has-text("提交")',

                'uni-button:has-text("提交")',

                'text=确认提交',

            ]

            for selector in preview_selectors:

                try:

                    btn = page.locator(selector).first

                    if btn.count() > 0 and btn.is_visible(timeout=2000):

                        # Screenshot before click
                        try:
                            page.screenshot(path="preview_before_click.png")
                        except:
                            pass

                        # Try multiple click methods
                        try:
                            btn.click(timeout=5000)
                        except:
                            try:
                                btn.dispatch_event('click')
                            except:
                                page.evaluate("arguments[0].click()", btn)
                        page.wait_for_timeout(3000)

                        # Screenshot after click
                        try:
                            page.screenshot(path="preview_after_click.png")
                        except:
                            pass
                        # Check URL after click
                        try:
                            current_url = page.url
                            logger.info(f"After preview click, URL: {current_url}")
                        except:
                            pass
                        # Check for popup/modal
                        try:
                            popup_check = page.evaluate("""() => {
                                const popups = document.querySelectorAll('uni-popup, .uni-popup, [class*=popup], [class*=modal]');
                                const visible = [];
                                popups.forEach(p => {
                                    const style = window.getComputedStyle(p);
                                    if (style.display !== 'none') visible.push(p.className.slice(0, 30));
                                });
                                return {count: visible.length, classes: visible};
                            }""")
                            logger.info(f"Popup check: {popup_check}")
                        except Exception as e:
                            logger.warning(f"Popup check failed: {e}")
                        logger.info(f"点击预览/确认: {selector}")

                        # Preview fix: populate the detail component from layyInfo (server draft data).
                        # The PC preview renders party sections from t.list[e.type] where
                        # e.type in ('yg','bg','dsr'); entries must use server field names.
                        try:
                            fix_result = None
                            for _attempt in range(3):
                                page.wait_for_timeout(1500)
                                fix_result = page.evaluate(r"""() => {
                                    const rootEl = document.querySelector('uni-app');
                                    if (!rootEl || !rootEl.__vue__) return {err:'no vue'};
                                    function tagOf(v){ return v && v.$options && (v.$options.name || v.$options._componentTag || v.$options.__name); }
                                    function findAll(v, out){ out=out||[]; if(!v) return out; out.push(v); for(const c of v.$children||[]) findAll(c,out); return out; }
                                    const det = findAll(rootEl.__vue__).find(v => tagOf(v) === 'detail');
                                    if (!det) return {err:'no detail comp'};
                                    const d = det.$data || det;
                                    const li = d.layyInfo || {};
                                    const hasLayy = !!(li.dsrs && li.dsrs.length);
                                    const srcParties = hasLayy ? li.dsrs : (d.dsrs || []);
                                    if (!srcParties.length && !(li.dlrs && li.dlrs.length)) return {retry: true, msg: 'layyInfo not loaded yet'};
                                    // 兜底补齐自然人缺失的派生字段，保证预览显示完整(与站点自身派生规则一致)
                                    const patchParty = (p) => {
                                        if (!p || typeof p !== 'object') return;
                                        const isZrr = !p.dwmc && (p.xm || p.zjhm);
                                        if (!isZrr) return;
                                        const id = (p.zjhm || '').trim();
                                        if (/^\d{17}[\dXx]$/.test(id)) {
                                            if (!p.csrq) p.csrq = id.substring(6,10) + '-' + id.substring(10,12) + '-' + id.substring(12,14);
                                            if (p.nl === undefined || p.nl === null || p.nl === '') {
                                                const birth = new Date(+id.substring(6,10), +id.substring(10,12)-1, +id.substring(12,14));
                                                const now = new Date();
                                                let age = now.getFullYear() - birth.getFullYear();
                                                if (now.getMonth() < birth.getMonth() || (now.getMonth() === birth.getMonth() && now.getDate() < birth.getDate())) age--;
                                                p.nl = String(age);
                                            }
                                        }
                                        if (p.gzdw === undefined || p.gzdw === null || p.gzdw === '') p.gzdw = '无';
                                        if (!p.zyMc) p.zyMc = '其他办事人员和有关人员';
                                    };
                                    srcParties.forEach(patchParty);
                                    const code2key = {'1501_030109-1':'yg','1501_030109-2':'bg','1501_030109-5':'dsr'};
                                    const list = {yg: [], bg: [], dsr: []};
                                    for (const p of srcParties) {
                                        let kk = code2key[p.ssdw];
                                        if (!kk) {
                                            const mc = (p.ssdwMc || '') + (p.dsrType || '') + (p.party_type || '') + (p.__role || '');
                                            kk = mc.indexOf('原告') >= 0 ? 'yg' : (mc.indexOf('被告') >= 0 ? 'bg' : (mc.indexOf('第三') >= 0 ? 'dsr' : ''));
                                        }
                                        if (kk) list[kk].push(p);
                                    }
                                    const dlrs = (li.dlrs && li.dlrs.length) ? li.dlrs : (d.dlrs || []);
                                    const newDsrs = srcParties.slice();
                                    const newDlrs = dlrs.slice();
                                    if (det.$set) {
                                        det.$set(d, 'list', list);
                                        det.$set(d, 'dsrs', newDsrs);
                                        det.$set(d, 'dlrs', newDlrs);
                                    } else {
                                        d.list = list; d.dsrs = newDsrs; d.dlrs = newDlrs;
                                    }
                                    det.list = list; det.dsrs = newDsrs; det.dlrs = newDlrs;
                                    if (det.$forceUpdate) det.$forceUpdate();
                                    return {ok: true, fromLayy: hasLayy, yg: list.yg.length, bg: list.bg.length, dsr: list.dsr.length, dlr: newDlrs.length};
                                }""")
                                if fix_result and not fix_result.get('retry'):
                                    break
                            logger.info(f"Preview data fix: {fix_result}")
                        except Exception as e:
                            logger.warning(f"Preview data fix failed: {e}")
                        return {'ok': True, 'action': 'clicked_preview', 'selector': selector}

                except:

                    continue

            # JS fallback

            result = page.evaluate("""() => {

                function isVisible(el) { 

                    if (!el) return false; 

                    const r = el.getBoundingClientRect(); 

                    return r.width > 0 && r.height > 0; 

                }

                const keywords = ['预览', '确认', '提交', '下一步'];

                const elements = document.querySelectorAll('button, uni-button, [class*="btn"], uni-view, view, span');

                for (const el of elements) {

                    const text = (el.innerText || '').trim();

                    // 跳过包含子元素的容器(避免误点进度条标签)

                    if (el.children.length > 0) continue;

                    if (keywords.some(k => text.includes(k)) && isVisible(el)) {

                        el.scrollIntoView({behavior: 'instant', block: 'center'});

                        el.click();

                        return {ok: true, text: text, tag: el.tagName};

                    }

                }

                return {err: 'no preview button'};

            }""")

            if result.get('ok'):

                page.wait_for_timeout(2000)

                logger.info(f"JS点击预览/确认: {result}")
                return {'ok': True, 'action': 'js_clicked', 'result': result}

            return {'ok': True, 'action': 'completed'}

        except Exception as e:

            return {'err': f'完善案件信息失败: {e}'}

