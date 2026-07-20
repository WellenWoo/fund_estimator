// 使用方法：
// 打开京东兑换页面，确保你已经人工登录
// 按 F12 打开开发者工具 → 切换到 Console（控制台） 标签
// 粘贴上面的代码，然后按回车执行
// 脚本会持续运行，每秒检查一次时间
// 到了 当天上午10:00 会自动完成勾选+兑换两步操作
(function() {
    // 目标时间：每天10:00
    const TARGET_HOUR = 10;
    const TARGET_MINUTE = 0;
    const CHECK_INTERVAL_MS = 1000; // 每秒检查一次
    
    console.log('🚗 京东积分兑换自动脚本已启动');
    console.log('⏰ 目标时间: 每天 ' + TARGET_HOUR + ':' + String(TARGET_MINUTE).padStart(2, '0'));
    
    let executedToday = false;
    
    function checkAndExecute() {
        const now = new Date();
        
        // 检查是否已达到目标时间（10:00）
        if (now.getHours() === TARGET_HOUR && now.getMinutes() >= TARGET_MINUTE) {
            
            // 防止同一天重复执行
            const todayStr = now.toDateString();
            if (executedToday) return;
            
            console.log('✅ 已到目标时间，开始执行兑换操作...');
            
            try {
                // ===== 第一步：勾选复选框 =====
                // 查找所有checkbox并尝试勾选
                const checkboxes = document.querySelectorAll('input[type="checkbox"]');
                let checkboxFound = false;
                
                checkboxes.forEach(function(cb) {
                    if (!cb.checked) {
                        cb.checked = true;
                        // 触发change事件以通知Vue/React等框架
                        cb.dispatchEvent(new Event('change', { bubbles: true }));
                        cb.dispatchEvent(new Event('input', { bubbles: true }));
                        checkboxFound = true;
                        console.log('✅ 已勾选复选框');
                    }
                });
                
                // 如果没找到标准checkbox，尝试通过文本内容定位
                if (!checkboxFound) {
                    const labels = document.querySelectorAll('label');
                    labels.forEach(function(label) {
                        if (label.textContent.includes('同意') || label.textContent.includes('条款')) {
                            const input = label.querySelector('input[type="checkbox"]');
                            if (input && !input.checked) {
                                input.checked = true;
                                input.dispatchEvent(new Event('change', { bubbles: true }));
                                input.dispatchEvent(new Event('input', { bubbles: true }));
                                checkboxFound = true;
                                console.log('✅ 已通过label勾选复选框');
                            }
                        }
                    });
                }
                
                setTimeout(function() {
                    
                    // ===== 第二步：点击兑换按钮 =====
                    // 多种策略查找按钮
                    
                    // 策略1: 按文字内容查找
                    const allElements = document.querySelectorAll('*');
                    let buttonClicked = false;
                    
                    allElements.forEach(function(el) {
                        if (el.childNodes.length > 0) {
                            el.childNodes.forEach(function(node) {
                                if (node.nodeType === Node.TEXT_NODE && 
                                    (node.textContent.includes('兑换') || 
                                     node.textContent.includes('抢购') ||
                                     node.textContent.includes('立即'))) {
                                    
                                    const parent = el.parentElement;
                                    if (parent && (parent.tagName === 'BUTTON' || 
                                                   parent.tagName === 'INPUT' ||
                                                   parent.classList.contains('btn') ||
                                                   parent.classList.contains('button') ||
                                                   parent.getAttribute('role') === 'button')) {
                                        parent.click();
                                        buttonClicked = true;
                                        console.log('✅ 已通过文字匹配点击按钮');
                                    }
                                }
                            });
                        }
                    });
                    
                    // 策略2: 按class名查找常见按钮类名
                    if (!buttonClicked) {
                        const commonBtnClasses = ['btn-primary', 'btn-submit', 'exchange-btn', 
                                                  'red-button', 'jd-btn', 'qiang-gou'];
                        
                        commonBtnClasses.forEach(function(cls) {
                            const btns = document.querySelectorAll('.' + cls);
                            btns.forEach(function(btn) {
                                if (!btn.disabled) {
                                    btn.click();
                                    buttonClicked = true;
                                    console.log('✅ 已通过class "' + cls + '" 点击按钮');
                                }
                            });
                        });
                    }
                    
                    // 策略3: 查找最后一个明显的提交/兑换按钮
                    if (!buttonClicked) {
                        const buttons = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"]'))
                                           .filter(function(b) { return !b.disabled; });
                        
                        if (buttons.length > 0) {
                            const lastBtn = buttons[buttons.length - 1];
                            lastBtn.click();
                            buttonClicked = true;
                            console.log('✅ 已点击最后一个可用按钮');
                        }
                    }
                    
                    if (buttonClicked) {
                        console.log('🎉 兑换操作已发送！请留意页面反馈');
                        executedToday = true;
                    } else {
                        console.warn('⚠️ 未找到可点击的按钮，请手动确认页面元素');
                    }
                    
                }, checkboxFound ? 500 : 100); // 勾选后稍作等待再点按钮
                
            } catch (e) {
                console.error('❌ 执行出错:', e);
            }
        }
    }
    
    // 启动定时器
    setInterval(checkAndExecute, CHECK_INTERVAL_MS);
    console.log('⏳ 监控中... 下次将在10:00触发');
})();