// ==UserScript==
// @name         JD 9积分兑换免费小保养 自动抢
// @namespace    https://github.com/local/
// @version      1.1.0
// @description  京东养车频道 - 每天10:00准时自动勾选「9积分兑换」并点击「兑换」按钮
// @author       Mavis
// @match        https://pro.m.jd.com/mall/active/3Rcw1NV6pjiUBpznNHooXjPNAicD/index.html*
// @match        https://pro.m.jd.com/*
// @icon         https://www.jd.com/favicon.ico
// @grant        GM_notification
// @grant        GM_setValue
// @grant        GM_getValue
// @run-at       document-end
// ==/UserScript==

(function () {
    'use strict';

    /* ===== 配置 ===== */
    const TARGET_HOUR = 10;
    const TARGET_MIN  = 0;
    const TARGET_SEC  = 0;
    const TRIGGER_WINDOW = 8;   // 10:00:00 ~ 10:00:07 视为可触发
    const TICK_MS = 100;        // 100ms 轮询，精度足够
    const RETRY_MAX = 20;       // 单次操作最大重试次数
    const RETRY_GAP = 150;      // 重试间隔

    /* ===== 状态 ===== */
    let fired = false;
    let lastResetDate = '';

    /* ===== 工具 ===== */
    const log = (...args) => console.log(
        '%c[JD-9积分]', 'color:#e1251b;font-weight:bold', new Date().toLocaleTimeString(), ...args
    );
    const sleep = ms => new Promise(r => setTimeout(r, ms));

    function notify(title, text) {
        if (typeof GM_notification === 'function') {
            try { GM_notification({ title, text, timeout: 5000 }); } catch (_) {}
        }
    }

    /* ===== 元素定位 ===== */
    /**
     * 找到「9积分兑换」对应的 radio（van-radio / 原生 radio / 充当 radio 的 div）
     * 策略：从包含目标文字的元素向上爬 2~6 层，找最近的"可选中容器"
     */
    function find9PointsRadio() {
        const ROOT_KEY = '9积分兑换';

        // 收集所有含文字的叶子元素
        const candidates = [...document.querySelectorAll('*')].filter(el => {
            if (el.children.length > 2) return false;
            const t = (el.innerText || el.textContent || '').trim();
            return t.includes(ROOT_KEY) && t.length < 50;
        });

        for (const leaf of candidates) {
            // 向上找祖先里第一个"看起来像 radio"的元素
            let p = leaf;
            for (let i = 0; i < 8 && p; i++) {
                // 原生 radio
                const r = p.querySelector?.('input[type="radio"]');
                if (r && r.offsetParent !== null) return { type: 'native', el: r, container: p };

                // Vant van-radio
                if (p.classList?.contains('van-radio')) return { type: 'vant', el: p, container: p };

                // role=radio
                const aria = p.querySelector?.('[role="radio"]');
                if (aria && aria.offsetParent !== null) return { type: 'aria', el: aria, container: p };

                // 自定义：可能是带特定 class 的圆点 / 整卡片可点
                if (p.classList?.contains('van-cell') ||
                    p.classList?.contains('van-card') ||
                    p.classList?.contains('item') ||
                    p.getAttribute?.('onclick')) {
                    return { type: 'custom', el: p, container: p };
                }
                p = p.parentElement;
            }
        }
        return null;
    }

    /**
     * 找到「兑换」按钮（多种文案 + 状态过滤）
     */
    function findExchangeButton() {
        const KEYWORDS = ['立即兑换', '马上兑换', '去兑换', '免费兑换', '兑换'];
        const DISABLED_CLASSES = ['van-button--disabled', 'disabled', 'is-disabled', 'btn-disabled'];

        const sels = [
            'button',
            'a',
            '[role="button"]',
            '.van-button',
            '.van-submit-bar__button',
            'div[onclick]',
            '.btn',
            '.button'
        ];

        const elements = document.querySelectorAll(sels.join(','));

        for (const el of elements) {
            // 可见性
            if (el.offsetParent === null && getComputedStyle(el).position !== 'fixed') continue;

            const text = (el.innerText || el.textContent || '').trim();

            // 必须正好是关键词，或以关键词开头（避免误中"已抢完..."）
            const matched = KEYWORDS.find(kw => text === kw || text.startsWith(kw));
            if (!matched) continue;

            // 必须可点
            if (el.disabled) continue;
            if (DISABLED_CLASSES.some(c => el.classList.contains(c))) continue;
            const style = getComputedStyle(el);
            if (style.pointerEvents === 'none') continue;
            if (style.opacity === '0') continue;

            return el;
        }
        return null;
    }

    /* ===== 点击（带兼容事件） ===== */
    function clickEl(el) {
        if (!el) return false;
        try {
            el.scrollIntoView({ block: 'center', behavior: 'instant' });
        } catch (_) {}
        try {
            el.click();
        } catch (_) {}
        // 兼容移动端 & 各种框架监听
        const evts = ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click', 'touchstart', 'touchend'];
        for (const t of evts) {
            try {
                el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window }));
            } catch (_) {}
        }
        return true;
    }

    /* ===== 主流程 ===== */
    async function performExchange() {
        log('⏰ 时间到，开始执行兑换流程');

        let radioOk = false, btnOk = false;
        const start = Date.now();

        for (let i = 0; i < RETRY_MAX && Date.now() - start < 8000; i++) {
            // 1) 勾选 9积分兑换
            if (!radioOk) {
                const r = find9PointsRadio();
                if (r) {
                    clickEl(r.el);
                    radioOk = true;
                    log(`✅ 已勾选 9积分兑换 (${r.type})`);
                }
            }

            // 2) 点击兑换按钮（确保 radio 选中后再点）
            if (radioOk && !btnOk) {
                await sleep(80);
                const btn = findExchangeButton();
                if (btn) {
                    clickEl(btn);
                    btnOk = true;
                    log('✅ 已点击兑换按钮');
                }
            }

            if (radioOk && btnOk) break;
            await sleep(RETRY_GAP);
        }

        const msg = btnOk
            ? '兑换已触发，请检查是否进入下一步（如确认弹窗、支付 0 元等）'
            : (radioOk ? '勾选成功但没找到兑换按钮，可能是还没到点' : '未找到 9积分兑换 选项');
        log(msg);
        notify('JD 9积分自动兑换', msg);

        // 记录最后执行日期（防当天重复触发 + 跨天重置）
        const today = new Date().toDateString();
        if (typeof GM_setValue === 'function') {
            GM_setValue('lastFireDate', today);
        }
        lastResetDate = today;
        fired = true;
    }

    /* ===== 倒计时（可选：每分钟打印） ===== */
    function tick() {
        const now = new Date();
        const h = now.getHours(), m = now.getMinutes(), s = now.getSeconds();
        const today = now.toDateString();

        // 跨天重置
        if (lastResetDate !== today) {
            const stored = (typeof GM_getValue === 'function') ? GM_getValue('lastFireDate', '') : '';
            fired = (stored === today);
            lastResetDate = today;
        }

        const inWindow = (h === TARGET_HOUR && m === TARGET_MIN && s >= TARGET_SEC && s <= TARGET_SEC + TRIGGER_WINDOW);

        if (inWindow && !fired) {
            performExchange();
        }

        // 离开窗口后解除 fired（让第二天能再次触发）
        if (fired && (h !== TARGET_HOUR || m > TARGET_MIN + 1)) {
            fired = false;
        }
    }

    /* ===== 启动 ===== */
    log('脚本已加载，等待每天 10:00 自动触发…');
    setInterval(tick, TICK_MS);

    // 立即跑一次，确认能找到元素（只 log，不点击）
    setTimeout(() => {
        const r = find9PointsRadio();
        const b = findExchangeButton();
        log('初始化检测 →',
            r ? 'radio 位置 OK' : 'radio 未找到（可能还没渲染）',
            '|',
            b ? '按钮已就绪' : '按钮暂未就绪（10:00 才会出现）'
        );
    }, 1500);

})();
