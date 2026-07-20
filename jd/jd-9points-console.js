/**
 * JD 9积分兑换免费小保养 - 浏览器控制台直接运行版
 *
 * 用法：
 *   1. 在目标页面按 F12 打开开发者工具
 *   2. 切到 Console（控制台）面板
 *   3. 把下面这一整段代码粘贴进去，回车
 *   4. 保持该标签页不关闭，10:00 自动执行
 *
 * 注意：标签页要一直开着，浏览器不能关。刷新页面需重新粘贴。
 */
(function () {
    'use strict';

    if (window.__JD9P_RUNNING__) {
        console.log('[JD-9积分] 脚本已经在跑了，不要重复执行');
        return;
    }
    window.__JD9P_RUNNING__ = true;

    const HOUR = 10, MIN = 0, WIN = 8, GAP = 100;
    let fired = false;

    const log = (...a) => console.log('%c[JD-9积分]', 'color:#e1251b;font-weight:bold',
        new Date().toLocaleTimeString(), ...a);
    const sleep = ms => new Promise(r => setTimeout(r, ms));

    function findRadio() {
        const leaves = [...document.querySelectorAll('*')]
            .filter(el => el.children.length <= 2 &&
                (el.innerText || '').includes('9积分兑换') &&
                (el.innerText || '').length < 50);
        for (const leaf of leaves) {
            let p = leaf;
            for (let i = 0; i < 8 && p; i++, p = p.parentElement) {
                if (!p) break;
                if (p.classList?.contains('van-radio')) return p;
                const r = p.querySelector?.('input[type="radio"]');
                if (r && r.offsetParent !== null) return r;
                const aria = p.querySelector?.('[role="radio"]');
                if (aria && aria.offsetParent !== null) return aria;
                if (p.classList?.contains('van-cell') || p.getAttribute?.('onclick')) return p;
            }
        }
        return null;
    }

    function findBtn() {
        const KW = ['立即兑换', '马上兑换', '去兑换', '免费兑换', '兑换'];
        const sels = 'button, a, [role="button"], .van-button, div[onclick]';
        for (const el of document.querySelectorAll(sels)) {
            if (el.offsetParent === null) continue;
            const t = (el.innerText || '').trim();
            if (!KW.find(k => t === k || t.startsWith(k))) continue;
            if (el.disabled) continue;
            if (el.classList.contains('van-button--disabled') ||
                el.classList.contains('disabled') ||
                el.classList.contains('is-disabled')) continue;
            const s = getComputedStyle(el);
            if (s.pointerEvents === 'none' || s.opacity === '0') continue;
            return el;
        }
        return null;
    }

    function clickEl(el) {
        if (!el) return;
        try { el.scrollIntoView({ block: 'center' }); } catch (_) {}
        try { el.click(); } catch (_) {}
        ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(t => {
            try { el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true })); } catch (_) {}
        });
    }

    async function run() {
        log('⏰ 10:00 到了，开始执行');
        let rOk = false, bOk = false;
        for (let i = 0; i < 20; i++) {
            if (!rOk) { const r = findRadio(); if (r) { clickEl(r); rOk = true; log('✅ 已勾选 9积分兑换'); } }
            if (rOk && !bOk) { await sleep(80); const b = findBtn(); if (b) { clickEl(b); bOk = true; log('✅ 已点击兑换按钮'); } }
            if (rOk && bOk) break;
            await sleep(150);
        }
        log(bOk ? '🎉 兑换已触发，请看页面是否进入下一步' :
            (rOk ? '⚠️ 勾选成功但没找到兑换按钮' : '❌ 没找到 9积分兑换 选项'));
        fired = true;
    }

    setInterval(() => {
        const n = new Date();
        if (n.getHours() === HOUR && n.getMinutes() === MIN &&
            n.getSeconds() >= 0 && n.getSeconds() <= WIN && !fired) {
            run();
        }
        if (fired && (n.getHours() !== HOUR || n.getMinutes() > MIN + 1)) fired = false;
    }, GAP);

    log('控制台版已启动，每天 10:00 自动执行。');
    log('当前页面元素检测：', findRadio() ? '✅ radio 已识别' : '⚠️ radio 暂未出现',
        '|', findBtn() ? '✅ 按钮已就绪' : '⚠️ 按钮未就绪（10:00 才会激活）');
})();
