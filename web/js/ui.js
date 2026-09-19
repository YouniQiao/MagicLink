// DOM 帮手、图标、Toast、模态框

export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'dataset' && typeof v === 'object') Object.assign(el.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') {
        el.addEventListener(k.slice(2).toLowerCase(), v);
      } else el.setAttribute(k, v === true ? '' : v);
    }
  }
  append(el, kids);
  return el;
}

export function append(el, kids) {
  for (const kid of kids.flat(4)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }

// 设置子节点。**别用原生的 replaceChildren**：它按 WebIDL 规则把每个参数转成
// 节点或字符串，`null` 会变成一个内容为 "null" 的文本节点（`undefined` 同理），
// 于是页面上凭空多出一个孤零零的 null。踩过两次，都是「这个元素该不该渲染」
// 的三元表达式返回了 null：
//   · 公开页没有标签时，筛选条 tagbar 是 null
//   · 空间列表只有一页时，分页器 pager() 返回 null
// 这两处首屏都看不出来（首屏走 h()，h() 会过滤），只有刷新列表时才冒出来。
// 这里和 h() 的 kids 用同一套规则：null / undefined / false 一律跳过。
export function setChildren(el, ...kids) {
  clear(el);
  append(el, kids);
  return el;
}

// ── 图标（stroke 风格，16px）────────────────────────────────────────────────
const PATHS = {
  user:     '<circle cx="8" cy="5.6" r="2.6"/><path d="M3.2 13.4c0-2.5 2.1-3.9 4.8-3.9s4.8 1.4 4.8 3.9"/>',
  gitbranch: '<circle cx="4.6" cy="4" r="1.7"/><circle cx="4.6" cy="12" r="1.7"/><circle cx="11.4" cy="6.6" r="1.7"/><path d="M4.6 5.7v4.6M6.3 6.6h3.4"/>',
  search:   '<circle cx="7" cy="7" r="4.4"/><path d="M10.4 10.4 14 14"/>',
  plus:     '<path d="M8 3.2v9.6M3.2 8h9.6"/>',
  pencil:   '<path d="M11.4 2.9l1.7 1.7L5.6 12 3 12.7 3.7 10z"/>',
  trash:    '<path d="M3 4.8h10M6.4 4.8V3.2h3.2v1.6M4.6 4.8l.6 8.4h5.6l.6-8.4"/>',
  share:    '<circle cx="12" cy="4.6" r="1.9"/><circle cx="4.2" cy="8" r="1.9"/><circle cx="12" cy="11.4" r="1.9"/><path d="M5.9 7.1l4.4-1.9M5.9 8.9l4.4 1.9"/>',
  copy:     '<rect x="5.4" y="5.4" width="7.6" height="7.6" rx="1.4"/><path d="M10.6 3.2H4.6A1.4 1.4 0 0 0 3.2 4.6v6"/>',
  folder:   '<path d="M2.6 4.4h3.8l1.2 1.6h5.8v6.6H2.6z"/>',
  users:    '<circle cx="6.2" cy="5.8" r="2.4"/><path d="M2.6 13c0-2 1.6-3.1 3.6-3.1S9.8 11 9.8 13"/><path d="M11 4.2a2 2 0 0 1 0 3.9M11.5 9.9c1.4.3 2.3 1.4 2.3 3.1"/>',
  settings: '<path d="M2.8 5h10.4M2.8 11h10.4"/><circle cx="6" cy="5" r="1.7"/><circle cx="10.2" cy="11" r="1.7"/>',
  logout:   '<path d="M6.2 3.2H3.4v9.6h2.8M8.6 8h5.2M11.4 5.6 13.8 8l-2.4 2.4"/>',
  link:     '<path d="M6.6 9.4a2.6 2.6 0 0 1 0-3.7l1.7-1.7a2.6 2.6 0 1 1 3.7 3.7l-.9.9"/><path d="M9.4 6.6a2.6 2.6 0 0 1 0 3.7l-1.7 1.7a2.6 2.6 0 1 1-3.7-3.7l.9-.9"/>',
  right:    '<path d="M6.2 3.8 10.4 8l-4.2 4.2"/>',
  left:     '<path d="M9.8 3.8 5.6 8l4.2 4.2"/>',
  check:    '<path d="M3.4 8.4l3 3 6.2-6.6"/>',
  x:        '<path d="M4 4l8 8M12 4l-8 8"/>',
  external: '<path d="M6.4 3.2H3.4v9.4h9.4v-3M9.2 3.2h3.6v3.6M12.8 3.2 7.4 8.6"/>',
  arrowl:   '<path d="M8 3.4 3.6 8 8 12.6M3.6 8h9.4"/>',
  bell:     '<path d="M4 6.6a4 4 0 0 1 8 0c0 3 1.2 4 1.2 4H2.8s1.2-1 1.2-4Z"/><path d="M6.6 12.4a1.6 1.6 0 0 0 2.8 0"/>',
  // 拖拽把手：六个圆点（stroke-linecap=round，所以极短的线段就是圆点）
  grip:     '<path d="M6 4h.01M6 8h.01M6 12h.01M10 4h.01M10 8h.01M10 12h.01"/>',
};

export function icon(name, size = 16, cls = 'ico') {
  const el = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  el.setAttribute('width', size); el.setAttribute('height', size);
  el.setAttribute('viewBox', '0 0 16 16');
  el.setAttribute('fill', 'none');
  el.setAttribute('stroke', 'currentColor');
  el.setAttribute('stroke-width', '1.5');
  el.setAttribute('stroke-linecap', 'round');
  el.setAttribute('stroke-linejoin', 'round');
  if (cls) el.setAttribute('class', cls);
  el.innerHTML = PATHS[name] || '';
  return el;
}

// ── Toast ───────────────────────────────────────────────────────────────────
export function toast(message, type = '') {
  const root = document.getElementById('toast-root');
  const el = h('div', { class: `toast ${type}`, text: message });
  root.append(el);
  setTimeout(() => {
    el.style.transition = 'opacity .25s';
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 260);
  }, 2400);
}

export const toastOk  = (m) => toast(m, 'ok');
export const toastErr = (m) => toast(m, 'err');

// ── 模态框 ──────────────────────────────────────────────────────────────────
export function modal({ title, sub, body, actions, width }) {
  const root = document.getElementById('modal-root');
  const box = h('div', { class: 'modal' },
    title ? h('h3', { text: title }) : null,
    sub ? h('div', { class: 'sub', text: sub }) : null,
    // body 单独一层：内容高了只滚中间，标题和按钮始终可见
    h('div', { class: 'modal-body' }, body),
    actions ? h('div', { class: 'modal-actions' }, actions) : null,
  );
  if (width) box.style.maxWidth = `${width}px`;

  const backdrop = h('div', {
    class: 'backdrop',
    onclick: (e) => { if (e.target === backdrop) close(); },
  }, box);

  const onKey = (e) => { if (e.key === 'Escape') close(); };
  function close() {
    document.removeEventListener('keydown', onKey);
    backdrop.remove();
  }
  document.addEventListener('keydown', onKey);
  root.append(backdrop);

  const first = box.querySelector('input, textarea, select');
  if (first) setTimeout(() => first.focus(), 30);

  return { close, box };
}

export function confirmDialog({ title, message, confirmText = '确定', danger = false }) {
  return new Promise((resolve) => {
    const m = modal({
      title,
      body: h('p', { class: 'muted', text: message }),
      actions: [
        h('button', { class: 'btn', text: '取消', onclick: () => { m.close(); resolve(false); } }),
        h('button', {
          class: `btn ${danger ? 'danger' : 'primary'}`, text: confirmText,
          onclick: () => { m.close(); resolve(true); },
        }),
      ],
    });
  });
}

// ── 小工具 ──────────────────────────────────────────────────────────────────
export function initials(name) {
  const s = String(name || '?').trim();
  if (!s) return '?';
  // 中文取首字（放进小圆里更清楚、也更可预期）；
  // 拉丁文取前两个词的首字母，只有一个词就取前两个字符。
  if (/[\u4e00-\u9fff]/.test(s)) return s.slice(0, 1);
  const words = s.split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return s.slice(0, 2);
}

export function hostOf(url) {
  try { return new URL(url).host.replace(/^www\./, ''); } catch { return url; }
}

export function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function debounce(fn, ms = 260) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// ── 公开页面共用的小部件 ────────────────────────────────────────────────────
// 首页（链接广场）和公开页（/u/xxx、/t/xxx）是两套独立脚本，但顶栏长得一样。
// 这三样放这里共用，别再各写一份——改一处漏一处最难查。

export function brand({ href = '/', title = 'MagicLink' } = {}) {
  return h('a', { class: 'brand', href, title },
    h('span', { class: 'mark', text: 'M' }), 'MagicLink');
}

// 顶栏右上角的账号区：已登录显示用户名，未登录显示「登录」。
// 三个顶栏都用它（公开页/首页 → /app，应用内 → 设置），只是跳转目标不同。
export function accountArea(user, { href = '/app', title = '进入 MagicLink' } = {}) {
  if (user) {
    return h('a', { class: 'userchip', href, title },
      h('span', { class: 'avatar', text: initials(user.display_name) }),
      h('span', { class: 'small', text: user.display_name }));
  }
  return h('a', { class: 'btn sm', href: '/app' }, '登录', icon('right'));
}

// 探当前会话。失败/未登录一律返回 null —— 公开页本身不需要登录，
// 顶栏显示错了可以忍，页面因此打不开不行。
export async function currentUser() {
  try {
    const r = await fetch('/api/me', { credentials: 'same-origin' });
    if (!r.ok) return null;
    const d = await r.json();
    return d && d.user ? d.user : null;
  } catch {
    return null;
  }
}
