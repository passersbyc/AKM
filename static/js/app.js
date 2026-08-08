/* AKM WebUI — 交互增强 */

// 数字滚动动画
function animateCounters() {
  document.querySelectorAll('[data-count]').forEach(el => {
    const target = parseInt(el.dataset.count, 10);
    if (isNaN(target) || target === 0) { el.textContent = target || 0; return; }

    const duration = 800;
    const start = performance.now();
    const startVal = 0;

    function step(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // easeOutQuart
      const ease = 1 - Math.pow(1 - progress, 4);
      const current = Math.round(startVal + (target - startVal) * ease);
      el.textContent = current;
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  });
}

// 进度条动画（从 0 到目标宽度）
function animateBars() {
  document.querySelectorAll('.tag-bar-fill').forEach(bar => {
    const targetWidth = bar.style.width;
    bar.style.width = '0%';
    bar.style.transition = 'none';

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        bar.style.transition = 'width 0.8s cubic-bezier(0.4, 0, 0.2, 1)';
        bar.style.width = targetWidth;
      });
    });
  });
}

// 卡片渐入（支持 IntersectionObserver）
function setupScrollAnimations() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.style.opacity = '1';
        entry.target.style.transform = 'translateY(0)';
      }
    });
  }, { threshold: 0.1 });

  document.querySelectorAll('.card, .stat-card').forEach(el => {
    // 已有 animate-in 类的元素由 CSS 动画处理，跳过
    if (el.classList.contains('animate-in')) return;
    el.style.opacity = '0';
    el.style.transform = 'translateY(12px)';
    el.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
    observer.observe(el);
  });
}

// 侧边栏：桌面折叠 / 移动端抽屉
function setupSidebar() {
  const backdrop = document.getElementById('sidebarBackdrop');
  if (!document.querySelector('.sidebar-toggle')) return;

  const closeDrawer = () => document.body.classList.remove('drawer-open');

  document.querySelectorAll('.sidebar-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      if (window.innerWidth <= 768) {
        document.body.classList.toggle('drawer-open');
      } else {
        document.documentElement.classList.toggle('sidebar-collapsed');
        localStorage.setItem('akm_sidebar_collapsed',
          document.documentElement.classList.contains('sidebar-collapsed') ? '1' : '0');
      }
    });
  });

  if (backdrop) backdrop.addEventListener('click', closeDrawer);

  if (localStorage.getItem('akm_sidebar_collapsed') === '1' && window.innerWidth > 768) {
    document.documentElement.classList.add('sidebar-collapsed');
  }
}

// 折叠态导航提示：侧边栏仅剩图标时，悬停显示名称气泡
function setupCollapsedTooltip() {
  let tip = null;
  const showTip = (text, x, y) => {
    if (!tip) {
      tip = document.createElement('div');
      tip.className = 'nav-tip';
      document.body.appendChild(tip);
    }
    tip.textContent = text;
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
    tip.classList.add('show');
  };
  const hideTip = () => { if (tip) tip.classList.remove('show'); };

  document.addEventListener('mouseover', (e) => {
    const item = e.target.closest('.nav-item');
    const collapsed = document.documentElement.classList.contains('sidebar-collapsed')
      && window.innerWidth > 768;
    if (!item || !collapsed) { hideTip(); return; }
    const r = item.getBoundingClientRect();
    const label = item.dataset.tip || item.getAttribute('title') || '';
    if (!label) { hideTip(); return; }
    showTip(label, r.right + 10, r.top + r.height / 2);
  }, { passive: true });
}

// 白天/夜晚模式切换（顶栏按钮；圆形扩散过渡，任何环境都不硬切）
function setupThemeToggle() {
  const btn = document.getElementById('themeToggle');
  if (!btn) return;
  let locked = false;
  btn.addEventListener('click', () => {
    if (locked) return;
    const root = document.documentElement;
    const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    const r = btn.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    root.style.setProperty('--theme-x', cx + 'px');
    root.style.setProperty('--theme-y', cy + 'px');

    const apply = () => {
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('akm_theme', next); } catch (e) {}
    };

    if (document.startViewTransition) {
      // View Transitions：新主题从按钮位置圆形扩散（clip-path 由 CSS 动画驱动）
      locked = true;
      document.startViewTransition(apply).finished.finally(() => { locked = false; });
    } else {
      // 兜底：手动纯色圆扩散（transform scale，GPU 丝滑），保证任何浏览器都有扩散动画
      locked = true;
      const mask = document.createElement('div');
      mask.className = 'theme-mask';
      mask.style.background = next === 'dark' ? 'rgb(14, 14, 26)' : 'rgb(247, 246, 243)';
      const d = Math.hypot(window.innerWidth, window.innerHeight);
      mask.style.setProperty('--s', Math.ceil(d / 20));
      mask.style.left = cx + 'px';
      mask.style.top = cy + 'px';
      document.body.appendChild(mask);
      requestAnimationFrame(() => requestAnimationFrame(() => mask.classList.add('expand')));
      setTimeout(apply, 240);          // 圆盖住屏幕后切换
      setTimeout(() => {
        mask.classList.add('fade');
        setTimeout(() => { mask.remove(); locked = false; }, 240);
      }, 500);
    }
  });
}

// ── 儿童模式顶栏切换 ──────────────────────────────
// 状态持久化：后端 config.json 为准（R-18 过滤依赖它），
// 另写 localStorage 供 UI 即时恢复；切换时播放平滑过渡动画。
function paintKidToggle(btn, on) {
  btn.classList.toggle('active', on);
  btn.setAttribute('aria-checked', on ? 'true' : 'false');
  const st = document.getElementById('kidToggleState');
  if (st) st.textContent = on ? '已开启' : '已关闭';
  btn.title = on ? '儿童模式已开启 · 点击切换到成人模式' : '成人模式 · 点击开启儿童模式（隐藏 R-18 作品）';
}

let _kidOverlay = null;
function showKidSwitching() {
  _kidOverlay = document.createElement('div');
  _kidOverlay.className = 'kid-switching-overlay';
  _kidOverlay.innerHTML = '<div class="kid-switching-spinner"></div>';
  document.body.appendChild(_kidOverlay);
  requestAnimationFrame(() => _kidOverlay.classList.add('show'));
}
function hideKidSwitching() {
  if (_kidOverlay) { _kidOverlay.remove(); _kidOverlay = null; }
}

function setupKidToggle() {
  const btn = document.getElementById('kidToggle');
  if (!btn) return;
  let locked = false;
  btn.addEventListener('click', () => {
    if (locked) return;
    locked = true;
    // 乐观更新按钮 UI（立即反馈），再请求后端
    const willOn = !btn.classList.contains('active');
    paintKidToggle(btn, willOn);
    showKidSwitching();
    fetch('/settings/kid-mode/toggle', { method: 'POST' })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          try { localStorage.setItem('akm_kid_mode', d.kid_mode ? '1' : '0'); } catch (e) {}
          try { sessionStorage.setItem('akm_kid_switched', '1'); } catch (e) {}
          showToast(d.kid_mode ? '👶 儿童模式已开启' : '儿童模式已关闭', d.kid_mode ? 'success' : 'info');
          // 遮罩淡入后刷新（过滤在后端渲染，需 reload 生效）
          setTimeout(() => { window.location.reload(); }, 380);
        } else {
          showToast(d.error || '(｡•́︿•̀｡) 切换失败呀～', 'error');
          paintKidToggle(btn, !willOn);
          hideKidSwitching();
          locked = false;
        }
      })
      .catch(() => {
        showToast('(｡•́︿•̀｡) 切换请求失败呀～', 'error');
        paintKidToggle(btn, !willOn);
        hideKidSwitching();
        locked = false;
      });
  });
}

// 刚完成模式切换的刷新：内容区淡入，避免生硬闪现
function setupKidEnter() {
  try {
    if (sessionStorage.getItem('akm_kid_switched')) {
      sessionStorage.removeItem('akm_kid_switched');
      const main = document.querySelector('.main-content');
      if (main) main.classList.add('kid-page-enter');
    }
  } catch (e) {}
}

// 未手动选择主题时，跟随系统实时变化（恢复 @media 的实时响应）
function setupThemeFollow() {
  try {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = (e) => {
      if (localStorage.getItem('akm_theme')) return; // 已手动选择，不覆盖
      document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
    };
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    else if (mq.addListener) mq.addListener(onChange); // 兼容旧 Safari
  } catch (e) {}
}

// 切换收藏：同步页面内所有指向该作品的收藏元素（data-fav-id 统一更新）
function toggleFav(id) {
  fetch(`/works/${id}/favorite`, { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      if (!d.success) { alert(d.error || '(｡•́︿•̀｡) 操作失败呀～'); return; }
      document.querySelectorAll(`[data-fav-id="${id}"]`).forEach(el => {
        if (el.classList.contains('work-fav')) {
          el.classList.toggle('on', d.favorite);
          el.textContent = d.favorite ? '♥' : '♡';
          el.title = d.favorite ? '已收藏（点击取消）' : '点击收藏';
        } else if (el.classList.contains('detail-badge')) {
          el.classList.toggle('badge-fav', d.favorite);
          el.textContent = d.favorite ? '♥ 已收藏' : '♡ 收藏';
          el.title = d.favorite ? '取消收藏' : '收藏';
        }
      });
    })
    .catch(() => alert('(｡•́︿•̀｡) 操作失败呀～'));
}

// 用系统默认应用打开作品（作品卡「打开本地」按钮）
function openWork(id) {
    fetch(`/works/${id}/open`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (!data.success) alert(data.error || '(｡•́︿•̀｡) 打开失败呀～');
        })
        .catch(() => alert('(｡•́︿•̀｡) 打开失败呀～'));
}

// 轻量提示条（右下角，成功/错误/加载）
function showToast(msg, type) {
    let t = document.getElementById('akmToast');
    if (!t) {
        t = document.createElement('div');
        t.id = 'akmToast';
        document.body.appendChild(t);
    }
    t.textContent = msg;
    t.className = 'akm-toast ' + (type || 'info');
    requestAnimationFrame(() => t.classList.add('show'));
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.remove('show'), type === 'loading' ? 30000 : 4200);
}

// 作品页导出弹窗（筛选范围 + 格式选择 + 进度状态一体）
function openExportModal() {
    const btn = document.getElementById('exportBtn');
    const mask = document.getElementById('exportMask');
    if (!btn || !mask) return;
    // 筛选范围摘要
    const scope = document.getElementById('exportScope');
    const cond = [];
    if (btn.dataset.q) cond.push('搜索「' + btn.dataset.q + '」');
    if (btn.dataset.author) cond.push('作者「' + btn.dataset.author + '」');
    if (btn.dataset.tags) cond.push('标签「' + btn.dataset.tags + '」');
    if (btn.dataset.type) cond.push(btn.dataset.type);
    if (btn.dataset.source) cond.push('来源「' + btn.dataset.source + '」');
    if (btn.dataset.fav === 'yes') cond.push('已收藏');
    scope.innerHTML = '';
    const b = document.createElement('b');
    b.textContent = '共 ' + (btn.dataset.total || '?') + ' 件作品';
    const p = document.createElement('span');
    p.textContent = cond.length ? ' · ' + cond.join(' · ') : '';
    scope.append(b, p);
    // 格式回显：默认选中配置的导出格式
    const defFmt = btn.dataset.fmt || 'folder';
    document.querySelectorAll('#exportFormats .export-fmt-card').forEach(c => {
        c.classList.toggle('active', c.dataset.fmt === defFmt);
    });
    // 重置状态与按钮
    const status = document.getElementById('exportStatus');
    status.style.display = 'none';
    status.className = 'export-status';
    const startBtn = document.getElementById('exportStartBtn');
    startBtn.disabled = false;
    startBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>开始导出';
    startBtn.onclick = startExport;
    const cancelBtn = document.getElementById('exportCancelBtn');
    cancelBtn.textContent = '取消';
    cancelBtn.onclick = closeExportModal;
    mask.classList.add('show');
}

function closeExportModal() {
    const mask = document.getElementById('exportMask');
    if (mask) mask.classList.remove('show');
}

// 格式卡切换（事件委托）
document.addEventListener('click', function (e) {
    const card = e.target.closest('.export-fmt-card');
    const wrap = document.getElementById('exportFormats');
    if (card && wrap && wrap.contains(card)) {
        wrap.querySelectorAll('.export-fmt-card').forEach(c => c.classList.remove('active'));
        card.classList.add('active');
    }
});

function getSelectedFmt() {
    const active = document.querySelector('#exportFormats .export-fmt-card.active');
    return active ? active.dataset.fmt : 'folder';
}

function updateExportStatus(html, type) {
    const status = document.getElementById('exportStatus');
    if (!status) return;
    status.innerHTML = html;
    status.className = 'export-status ' + (type || '');
    status.style.display = 'block';
}

function exportOpenFolder(dest) {
    fetch('/works/export/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'dest=' + encodeURIComponent(dest || ''),
    }).then(r => r.json()).then(x => { if (!x.success) showToast(x.error || '打开失败', 'error'); });
}

function startExport() {
    const btn = document.getElementById('exportBtn');
    const startBtn = document.getElementById('exportStartBtn');
    if (!btn || startBtn.disabled) return;
    const params = new URLSearchParams({
        q: btn.dataset.q || '', author: btn.dataset.author || '', tags: btn.dataset.tags || '',
        file_type: btn.dataset.type || '', source: btn.dataset.source || '', favorited: btn.dataset.fav || '',
        output_format: getSelectedFmt(),
    });
    startBtn.disabled = true;
    startBtn.innerHTML = '<span class="wb-export-spin"></span> 导出中…';
    updateExportStatus('正在准备导出…', 'loading');
    fetch('/works/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: params.toString(),
    })
        .then(r => r.json())
        .then(d => {
            if (!d.success || !d.task_id) {
                updateExportStatus(d.error || '导出失败', 'error');
                startBtn.disabled = false;
                startBtn.innerHTML = '重试';
                startBtn.onclick = startExport;
                return;
            }
            pollExportModal(d.task_id, 0);
        })
        .catch(() => {
            updateExportStatus('(｡•́︿•̀｡) 导出请求失败呀～', 'error');
            startBtn.disabled = false;
            startBtn.innerHTML = '重试';
            startBtn.onclick = startExport;
        });
}

function pollExportModal(taskId, elapsed) {
    const startBtn = document.getElementById('exportStartBtn');
    fetch('/works/export/status/' + taskId)
        .then(r => r.json())
        .then(d => {
            if (d.status === 'done') {
                updateExportStatus('<b>✓ 已导出 ' + d.exported + ' 件作品</b>', 'success');
                startBtn.disabled = false;
                startBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="8" y1="14" x2="16" y2="14"/></svg>打开文件夹';
                startBtn.onclick = function () { exportOpenFolder(d.destination); };
                const cancelBtn = document.getElementById('exportCancelBtn');
                cancelBtn.textContent = '完成';
                cancelBtn.onclick = closeExportModal;
                showToast('✓ 已导出 ' + d.exported + ' 件作品', 'success');
            } else if (d.status === 'failed') {
                updateExportStatus(d.error || '导出失败', 'error');
                startBtn.disabled = false;
                startBtn.innerHTML = '重试';
                startBtn.onclick = startExport;
            } else {
                updateExportStatus('正在导出中…（已 ' + elapsed + 's）', 'loading');
                setTimeout(function () { pollExportModal(taskId, elapsed + 1); }, 1000);
            }
        })
        .catch(() => {
            updateExportStatus('(｡•́︿•̀｡) 查询导出状态失败呀～', 'error');
            startBtn.disabled = false;
            startBtn.innerHTML = '重试';
            startBtn.onclick = startExport;
        });
}

// 导出结果面板（路径 + 打开文件夹）
function showExportResult(d) {
    const old = document.getElementById('akmExportResult');
    if (old) old.remove();
    const panel = document.createElement('div');
    panel.id = 'akmExportResult';
    panel.className = 'export-result';
    const head = document.createElement('div');
    head.className = 'export-result-head';
    head.textContent = `✓ 已导出 ${d.exported} 件作品`;
    const path = document.createElement('div');
    path.className = 'export-result-path';
    path.textContent = d.destination || '';
    path.title = d.destination || '';
    const foot = document.createElement('div');
    foot.className = 'export-result-foot';
    const openBtn = document.createElement('button');
    openBtn.className = 'export-result-btn';
    openBtn.textContent = '打开文件夹';
    openBtn.onclick = function () {
        fetch('/works/export/open', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'dest=' + encodeURIComponent(d.destination || ''),
        }).then(r => r.json()).then(x => { if (!x.success) showToast(x.error || '打开失败', 'error'); });
    };
    const closeBtn = document.createElement('button');
    closeBtn.className = 'export-result-btn ghost';
    closeBtn.textContent = '关闭';
    closeBtn.onclick = function () { panel.remove(); };
    foot.append(openBtn, closeBtn);
    panel.append(head, path, foot);
    document.body.appendChild(panel);
    requestAnimationFrame(() => panel.classList.add('show'));
    setTimeout(() => panel.classList.remove('show'), 20000);
}

// 详情页：导出单个作品
function exportWork(id) {
    fetch(`/works/${id}/export`, { method: 'POST' })
        .then(r => r.json())
        .then(d => {
            if (d.success) {
                showToast(`✓ 已导出 1 件作品`, 'success');
                showExportResult(d);
            } else showToast(d.error || '导出失败', 'error');
        })
        .catch(() => showToast('(｡•́︿•̀｡) 导出请求失败呀～', 'error'));
}

// 隐私模式：隐藏封面 + 陌生化元数据（开关在设置页）
const PRIVACY_TEXT_SELECTOR = [
  '.w-title', '.w-author', '.w-tag', '.work-title', '.work-author', '.work-tag',
  '.work-type-badge', '.w-row-title', '.w-row-sub', '.w-type',
  '.recommend-title', '.reason-tag', '.series-count',
  '.top-title', '.top-sub', '.top-name', '.item-title',
  '.tag-name', '.cloud-tag',
  '.detail-title', '.detail-tag', '.detail-desc',
  '.author-name', '.author-chip-name',
  '.dc-url', '.dc-author-name', '.dc-type',
  '.dl-url', '.dl-author-name',
  '.up-author-name', '.up-author-sub', '.ag-name',
  '.w-id', '.work-id',
  '.w-series', '.w-row-series', '.series-title', '.series-author',
  '.w-rating', '.w-rating-sm',
  '.act-title', '.act-time',
  '.au-name', '.au-uid', '.au-tag',
  '.imp-recent-title',
].join(', ');

// 生僻字池：形似真实汉字但几乎没人认识
const PRIVACY_POOL = '龘靐齉爩鱻麤龗灪厵爨癵籱饢驫顣鸙虋靊霪靂鸞齑齾鼇灩爚灪爩';

function obfuscateString(s) {
  if (!s) return s;
  return Array.from(s).map(c => {
    if (/\s/.test(c)) return c;
    return PRIVACY_POOL[Math.floor(Math.random() * PRIVACY_POOL.length)];
  }).join('');
}

function applyPrivacyText(on) {
  document.querySelectorAll(PRIVACY_TEXT_SELECTOR).forEach(el => {
    // title 属性（悬停提示）一并乱码
    if (on && el.hasAttribute('title') && !el.hasAttribute('data-pri-title')) {
      el.setAttribute('data-pri-title', el.getAttribute('title'));
      el.setAttribute('title', obfuscateString(el.getAttribute('title')));
    } else if (!on && el.hasAttribute('data-pri-title')) {
      el.setAttribute('title', el.getAttribute('data-pri-title'));
      el.removeAttribute('data-pri-title');
    }
    // 文本节点逐字替换（保留 DOM 结构，可逆）
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (on) {
        node.__privacyOrig = node.data;
        node.data = obfuscateString(node.data);
      } else if (node.__privacyOrig !== undefined) {
        node.data = node.__privacyOrig;
      }
    }
  });
}

function setPrivacyMode(on) {
  document.documentElement.classList.toggle('privacy-mode', on);
  applyPrivacyText(on);
  localStorage.setItem('akm_privacy', on ? '1' : '0');
}

// 顶栏返回按钮：同站有历史则返回上一页，否则回仪表盘
function setupTopbarBack() {
  const btn = document.getElementById('topbarBack');
  if (!btn) return;
  btn.addEventListener('click', () => {
    try {
      const ref = new URL(document.referrer);
      if (ref.origin === location.origin && history.length > 1) {
        history.back();
        return;
      }
    } catch (e) { /* 无 referrer */ }
    location.href = '/';
  });
}

// 悬停预取：导航/分页/查看全部链接悬停时预加载页面
function setupPrefetch() {
  document.addEventListener('mouseover', (e) => {
    const a = e.target.closest('a[href^="/"]');
    if (!a || a.dataset.prefetched) return;
    a.dataset.prefetched = '1';
    if (a.matches('.nav-item, .w-page, .ag-more, .ag-more-bar a, .w-series')) {
      const link = document.createElement('link');
      link.rel = 'prefetch';
      link.href = a.href;
      document.head.appendChild(link);
    }
  }, { passive: true });
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
  animateCounters();
  animateBars();
  setupScrollAnimations();
  setupSidebar();
  setupCollapsedTooltip();
  setupThemeToggle();
  setupKidToggle();
  setupKidEnter();
  setupThemeFollow();
  setupTopbarBack();
  setupPrefetch();
  // 作品页导出按钮
  // 作品页导出按钮（onclick="openExportModal()" 内联绑定，见 works.html）
  // 刷新后若隐私模式已记忆，恢复乱码
  if (document.documentElement.classList.contains('privacy-mode')) {
    applyPrivacyText(true);
  }
});
