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

// 初始化
document.addEventListener('DOMContentLoaded', () => {
  animateCounters();
  animateBars();
  setupScrollAnimations();
});
