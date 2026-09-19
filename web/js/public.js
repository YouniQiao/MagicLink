// 对外公开页：独立运行，不依赖主应用、不需要登录。
// 数据来自 /api/public/*，只有勾了「对外公开」的链接会出现在这里。
import {
  h,
  icon,
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

  // 「复制备注」按钮。整张卡是一个 <a>，所以这里有两个坎：
  //   1. 必须自己掐断事件（preventDefault + stopPropagation），否则点它会顺带打开链接；
  //   2. 用 <span role="button"> 而不是 <button> —— <a> 的内容模型不允许出现交互内容，
  //      浏览器虽然能渲染，但嵌套本身是不合法的。
  // 反馈不用 toast：公开页没有 #toast-root（那是主应用才有的），会直接报错。
  // 改成图标自己翻成对勾，顺带能看出到底复制的是哪一张卡。
  let copyBtn = null;
  let timer = null;

  function flash(ok) {
    if (!copyBtn) return;
    copyBtn.classList.toggle('done', ok);
    setChildren(copyBtn, icon(ok ? 'check' : 'x', 14));
    clearTimeout(timer);
    timer = setTimeout(() => {
      copyBtn.classList.remove('done');
      setChildren(copyBtn, icon('copy', 14));
    }, 1400);
  }

  async function copyNote() {
    try {
      await navigator.clipboard.writeText(it.description);
      flash(true);
    } catch {
      flash(false);   // 非安全上下文（纯 http 的非 localhost）下会走到这里
    }
  }

  if (it.description) {
    copyBtn = h('span', {
      class: 'pubcopy', role: 'button', tabindex: '0', title: '复制备注',
      onclick: (e) => { e.preventDefault(); e.stopPropagation(); copyNote(); },
      onkeydown: (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault(); e.stopPropagation(); copyNote();
        }
      },
    }, icon('copy', 14));
  }

  return h('a', {
    class: 'pubcard', href: it.url, target: '_blank', rel: 'noopener noreferrer',
  },
    h('div', { class: 'favbox' }, fav),
    h('div', { class: 'pubmain' },
      h('div', { class: 'pubtitle' },
        h('span', { class: 'label', text: it.title || it.url }), icon('external')),
      it.description ? h('div', { class: 'pubdesc', text: it.description }) : null,
      // 没有备注可复制时（也就没有按钮）整行不渲染，免得留一条空行
      copyBtn ? h('div', { class: 'pubmeta' }, copyBtn) : null),
  );
}

function render(data, user) {
  const state = { q: '' };
  const list = h('div', { class: 'publist' });

  function paint() {
    const q = state.q.toLowerCase();
    const groups = data.groups
      .map((g) => ({
        ...g,
        links: g.links.filter((it) => {
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
            h('div', { text: data.total ? '换个关键词试试。'
              : '对方还没有把链接设为「对外公开」。' })),
    );
    counter.textContent = state.q
      ? `筛选出 ${shown} / ${data.total} 条`
      : `共 ${data.total} 条`;
  }

  const searchIn = h('input', { class: 'input', placeholder: '搜索标题、网址、备注' });
  searchIn.addEventListener('input', debounce(() => { state.q = searchIn.value.trim(); paint(); }));

  // 条数跟着搜索框走（筛选时它会变成「筛选出 X / Y 条」），不占顶栏
  const counter = h('span', { class: 'small muted pubcount' });
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
