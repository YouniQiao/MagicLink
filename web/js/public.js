// 对外公开页：独立运行，不依赖主应用、不需要登录。
// 数据来自 /api/public/*，只有勾了「对外公开」的链接会出现在这里。
import {
  h,
  icon,
  hostOf,
  debounce,
  brand,
  accountArea,
  currentUser,
  setChildren,
} from './ui.js';

const app = document.getElementById('app');

function parsePath() {
  const seg = location.pathname.split('/').filter(Boolean);
  if (seg.length >= 2 && (seg[0] === 'u' || seg[0] === 't')) {
    return { kind: seg[0] === 'u' ? 'personal' : 'team', key: seg[1] };
  }
  return null;
}

async function load(target) {
  const url = target.kind === 'personal'
    ? `/api/public/u/${encodeURIComponent(target.key)}`
    : `/api/public/t/${encodeURIComponent(target.key)}`;
  const res = await fetch(url, { credentials: 'omit' });
  if (!res.ok) {
    let detail = '这个公开页不存在或没有开启';
    try { detail = (await res.json()).detail || detail; } catch { /* 忽略 */ }
    return { error: detail, status: res.status };
  }
  return { data: await res.json() };
}

function linkCard(it) {
  const fav = it.favicon
    ? h('img', { src: it.favicon, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer',
                 onerror: (e) => { e.target.style.display = 'none'; } })
    : icon('link');
  return h('a', {
    class: 'pubcard', href: it.url, target: '_blank', rel: 'noopener noreferrer',
    title: it.description || it.title || it.url,
  },
    h('div', { class: 'favbox' }, fav),
    h('div', { class: 'pubmain' },
      h('div', { class: 'pubtitle' },
        h('span', { class: 'label', text: it.title || it.url }), icon('external')),
      it.description ? h('div', { class: 'pubdesc', text: it.description }) : null,
      h('div', { class: 'pubmeta' },
        h('span', { class: 'pubhost', text: hostOf(it.url) }),
        ...(it.tags || []).map((t) => h('span', { class: 'tag', text: t })))),
  );
}

function render(data, user) {
  const state = { q: '', tag: '' };
  const list = h('div', { class: 'publist' });

  function paint() {
    const q = state.q.toLowerCase();
    const groups = data.groups
      .map((g) => ({
        ...g,
        links: g.links.filter((it) => {
          if (state.tag && !(it.tags || []).includes(state.tag)) return false;
          if (!q) return true;
          const hay = [it.title, it.url, it.description, (it.tags || []).join(' ')]
            .join(' ').toLowerCase();
          return q.split(/\s+/).every((part) => hay.includes(part));
        }),
      }))
      .filter((g) => g.links.length);

    const shown = groups.reduce((n, g) => n + g.links.length, 0);

    setChildren(list, 
      groups.length
        ? h('div', null, ...groups.map((g) => h('section', { class: 'pubgroup' },
            h('div', { class: 'pubgrouphead' },
              icon('folder', 13),
              h('span', { text: g.name }),
              h('span', { class: 'cnt', text: g.links.length })),
            h('div', { class: 'pubgrid' }, ...g.links.map(linkCard)))))
        : h('div', { class: 'empty' },
            h('div', { class: 't', text: data.total ? '没有匹配的链接' : '还没有公开的链接' }),
            h('div', { text: data.total ? '换个关键词或标签试试。'
              : '对方还没有把链接设为「对外公开」。' })),
    );
    counter.textContent = state.q || state.tag
      ? `筛选出 ${shown} / ${data.total} 条`
      : `共 ${data.total} 条`;
    syncPills();
  }

  const searchIn = h('input', { class: 'input', placeholder: '搜索标题、网址、标签' });
  searchIn.addEventListener('input', debounce(() => { state.q = searchIn.value.trim(); paint(); }));

  // 条数跟着搜索框走（筛选时它会变成「筛选出 X / Y 条」），不占顶栏
  const counter = h('span', { class: 'small muted pubcount' });
  const tagbar = data.tags.length
    ? h('div', { class: 'tagbar' },
        h('button', { class: 'pill', dataset: { tag: '' }, text: '全部' }),
        ...data.tags.map((t) => h('button', { class: 'pill', dataset: { tag: t }, text: t })))
    : null;

  function syncPills() {
    if (!tagbar) return;
    [...tagbar.children].forEach((b) =>
      b.classList.toggle('active', (b.dataset.tag || '') === state.tag));
  }

  if (tagbar) {
    tagbar.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      const t = btn.dataset.tag || '';
      state.tag = state.tag === t ? '' : t;   // 再点一次取消
      syncPills();
      paint();
    });
  }

  setChildren(app, 
    h('header', { class: 'pubhead' },
      h('div', { class: 'pubheadtop' },
        brand({ title: '返回链接广场' }), accountArea(user)),
      h('h1', { class: 'pubname', text: data.name }),
      h('p', { class: 'pubsub', text: data.kind === 'team'
        ? `团队公开链接${data.owner_name ? ` · 由 ${data.owner_name} 维护` : ''} · 只读展示`
        : '公开链接 · 只读展示' })),
    h('div', { class: 'pubbartools' },
      h('div', { class: 'search' }, icon('search'), searchIn),
      counter),
    tagbar,
    list,
    h('footer', { class: 'pubfoot' },
      h('span', { text: '由 MagicLink 生成 · 内容更新会实时同步' })),
  );
  paint();
}

function renderError(msg, user) {
  setChildren(app, 
    h('div', { class: 'pubhead' },
      h('div', { class: 'pubheadtop' },
        brand({ title: '返回链接广场' }), accountArea(user))),
    h('div', { class: 'empty' },
      h('div', { class: 't', text: '打不开这个公开页' }),
      h('div', { text: msg })),
  );
}

(async () => {
  const target = parsePath();
  // 会话探测只为顶栏那一个按钮，别让它拖慢正文 —— 和取数据并行。
  // 探测失败不影响公开页本身（这里本来就不需要登录）。
  const [user, res] = await Promise.all([
    currentUser(),
    target ? load(target) : Promise.resolve(null),
  ]);
  if (!target) { renderError('地址格式不对，应该是 /u/<用户名> 或 /t/<团队地址>。', user); return; }
  if (res.error) { renderError(res.error, user); return; }
  document.title = `${res.data.name} · 公开链接`;
  render(res.data, user);
})();
