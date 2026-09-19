// 首页：链接广场。
// 列出所有开启「对外公开」的团队空间和个人空间，访客挑一个进去看，不需要登录。
// 顶栏会读当前会话：已登录显示用户名（点了进 /app），未登录显示「登录」。
import { h, icon, brand, accountArea, currentUser } from './ui.js';

const app = document.getElementById('app');

function spaceCard(s) {
  const isTeam = s.kind === 'team';
  return h('a', { class: 'spacecard', href: s.url },
    h('div', { class: 'spaceicon' }, icon(isTeam ? 'users' : 'user', 16)),
    h('div', { class: 'spacemain' },
      h('div', { class: 'spacename' },
        h('span', { class: 'label', text: s.name }), icon('right')),
      h('div', { class: 'spacesub',
        text: isTeam ? `由 ${s.owner_name} 维护` : `@${s.username}` }),
      h('div', { class: 'spacemeta' },
        h('span', { class: 'spacecount', text: `${s.link_count} 条链接` }),
        ...(s.tags || []).map((t) => h('span', { class: 'tag', text: t })))),
  );
}

function section(title, items) {
  if (!items.length) return null;
  return h('section', { class: 'pubgroup' },
    h('div', { class: 'pubgrouphead' },
      h('span', { text: title }),
      h('span', { class: 'cnt', text: `${items.length} 个` })),
    h('div', { class: 'spacegrid' }, ...items.map(spaceCard)),
  );
}

function render(d, user) {
  const teams = d.teams || [];
  const people = d.people || [];

  const body = d.total
    ? h('div', null,
        section('团队空间', teams),
        section('个人空间', people))
    : h('div', { class: 'empty', style: { marginTop: '48px' } },
        h('div', { class: 't', text: '还没有公开的链接空间' }),
        h('div', { text: '登录后在「设置」里开启自己的公开页，或由团队拥有者开启团队公开页。' }),
        h('a', { class: 'btn primary', href: '/app' }, '进入 MagicLink'));

  app.replaceChildren(
    h('header', { class: 'pubhead' },
      h('div', { class: 'pubheadtop' }, brand({ title: '链接广场' }), accountArea(user)),
      h('h1', { class: 'pubname', text: '链接广场' }),
      h('p', { class: 'pubsub', text: user
        ? '这里是大家公开出来的链接集合，挑一个看看。'
        : '这里是大家公开出来的链接集合，挑一个看看。不需要登录。' })),
    body,
    h('footer', { class: 'pubfoot' },
      h('span', { text: 'MagicLink · 只有被标记为「对外公开」的链接会出现在这里' })),
  );
  document.title = 'MagicLink · 链接广场';
}

function renderError(msg, user) {
  app.replaceChildren(
    h('div', { class: 'pubhead' },
      h('div', { class: 'pubheadtop' }, brand({ title: '链接广场' }), accountArea(user))),
    h('div', { class: 'empty' },
      h('div', { class: 't', text: '加载失败' }),
      h('div', { text: msg }),
      h('a', { class: 'btn', href: '/' }, '重试')),
  );
}

(async () => {
  const user = await currentUser();
  try {
    const res = await fetch('/api/public/directory', { credentials: 'omit' });
    if (!res.ok) { renderError(`服务返回 ${res.status}`, user); return; }
    render(await res.json(), user);
  } catch (e) {
    renderError(String(e && e.message ? e.message : e), user);
  }
})();
