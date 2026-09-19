import { api, onUnauthorized, ApiError } from './api.js';
import {
  h,
  clear,
  icon,
  toastOk,
  toastErr,
  modal,
  accountArea,
  setChildren,
} from './ui.js';
import { renderPersonalSpace } from './personal.js';
import { renderTeamSpace } from './team.js';

export const state = {
  me: null,
  teams: [],
  groups: [],
};

const appEl = () => document.getElementById('app');

// ── 数据 ────────────────────────────────────────────────────────────────────
export async function loadMe() {
  try {
    const d = await api.get('/api/me');
    state.me = d.user;
    state.teams = d.teams || [];
    return true;
  } catch {
    state.me = null;
    state.teams = [];
    return false;
  }
}

export async function loadGroups() {
  try {
    const d = await api.get('/api/local/groups');
    state.groups = d.items || [];
  } catch { state.groups = []; }
  return state.groups;
}

export async function refreshSidebars() {
  await Promise.all([loadMe(), loadGroups()]);
}

// ── 路由 ────────────────────────────────────────────────────────────────────
function parseHash() {
  const raw = decodeURI(location.hash.replace(/^#/, '')) || '/';
  const [path, query] = raw.split('?');
  return {
    seg: path.split('/').filter(Boolean),
    q: new URLSearchParams(query || ''),
  };
}

export function go(path) {
  if (location.hash === `#${path}`) { render(); return; }
  location.hash = path;
}

// ── 通用布局 ────────────────────────────────────────────────────────────────
export function layout({ active, title, sub, actions, body, hideSide = false,
                         wide = false }) {
  return h('div', { class: 'shell' },
    topbar(),
    h('div', { class: 'body' },
      hideSide ? null : sidebar(active),
      h('div', { class: 'content' },
        // 空间页（个人/团队）用宽版：跟公开页同一个 1560px 上限，
        // 宽屏下两边的卡片列数和宽度才对得上。
        h('div', { class: `wrap${wide ? ' wide' : ''}` },
          h('div', { class: 'page-head' },
            h('div', null,
              h('div', { class: 'page-title', text: title }),
              sub ? h('div', { class: 'page-sub', text: sub }) : null),
            actions ? h('div', { class: 'head-actions' }, actions) : null),
          body))));
}

function topbar() {
  const u = state.me;
  return h('div', { class: 'topbar' },
    h('a', { href: '#/', class: 'brand' },
      h('span', { class: 'mark', text: 'M' }), 'MagicLink'),
    h('div', { class: 'topbar-spacer' }),
    u ? accountArea(u, { href: '#/settings', title: '账号设置' }) : null);
}

function sidebar(active) {
  const nav = (key, label, iconName, href, count) =>
    h('a', { class: `navitem ${active === key ? 'active' : ''}`, href },
      icon(iconName), h('span', { class: 'txt', text: label }),
      count === undefined || count === null ? null
        : h('span', { class: 'count', text: String(count) }));

  // 团队是独立的顶级空间，所以一个个列在侧边栏；
  // 分组是空间内部的结构（团队空间里也一样），只出现在各自的空间页里，不占侧边栏。
  // 侧边栏这一行很窄，只甩一个裸数字会被误读成链接数（真的被问过），
  // 所以带上单位让数字自解释；悬停再给成员数 + 链接数的完整信息。
  const teamItems = state.teams.map((t) =>
    h('a', {
      class: `navitem ${active === `t${t.id}` ? 'active' : ''}`,
      href: `#/team/${t.id}`,
      title: `${t.name} · ${t.member_count} 位成员 · ${t.link_count + t.shared_count} 条链接`,
    },
      icon('users'), h('span', { class: 'txt', text: t.name }),
      h('span', { class: 'count', text: `${t.member_count} 人` })));

  return h('div', { class: 'sidebar' },
    h('div', { class: 'side-label', text: '个人' }),
    nav('home', '工作台', 'right', '#/'),
    nav('space', '我的空间', 'link', '#/space'),

    h('div', { class: 'side-label', text: '团队' }),
    ...(teamItems.length ? teamItems
      : [h('div', { class: 'navitem nav-ghost', style: { cursor: 'default' } },
          h('span', { class: 'txt', text: '还没有加入团队' }))]),
    h('button', {
      class: 'navitem nav-ghost', onclick: () => promptJoinTeam(),
    }, icon('plus'), h('span', { class: 'txt', text: '加入 / 创建团队' })),

    h('div', { class: 'side-label', text: '账号' }),
    nav('settings', '设置', 'settings', '#/settings'),
    h('button', {
      class: 'navitem nav-ghost',
      onclick: async () => { await api.post('/api/auth/logout'); await boot(); },
    }, icon('logout'), h('span', { class: 'txt', text: '退出登录' })),

    // 链接广场是应用之外的页面（公开浏览用）。
    // 单独一组并沿用「个人 / 团队 / 账号」那种小标题分隔，而不是加个分隔线——
    // 一来和现有设计语言一致，二来能让「退出登录」保持在最底部（符合惯例）。
    h('div', { class: 'side-label', text: '公开页' }),
    h('a', { class: 'navitem', href: '/', title: '去链接广场（公开浏览）' },
      icon('external'), h('span', { class: 'txt', text: '链接广场' })),
  );
}

// ── 登录页 ──────────────────────────────────────────────────────────────────
function loginView(mode = 'login') {
  let error = '';
  const userIn = h('input', { class: 'input', placeholder: '用户名', autocomplete: 'username' });
  const pwIn = h('input', { class: 'input', type: 'password', placeholder: '密码', autocomplete: 'current-password' });
  const nameIn = h('input', { class: 'input', placeholder: '昵称（可留空）' });
  const errBox = h('div', { class: 'form-error', style: { display: 'none' } });
  const isReg = mode === 'register';

  // GitCode 回调失败时会把原因放在 ?auth_error=。
  // 登录页可能被渲染不止一次（未登录时 401 会再触发一次 render），每次渲染都是
  // 新的 DOM，所以这个提示要一直保留到用户真正操作（提交表单/切换注册）为止。
  const authError = peekAuthError();
  if (authError) {
    errBox.textContent = authError;
    errBox.style.display = '';
  }

  async function submit(e) {
    e?.preventDefault();
    clearAuthError();
    errBox.style.display = 'none';
    const username = userIn.value.trim();
    const password = pwIn.value;
    if (!username || !password) {
      errBox.textContent = '请填写用户名和密码'; errBox.style.display = ''; return;
    }
    try {
      if (isReg) {
        await api.post('/api/auth/register', {
          username, password, display_name: nameIn.value.trim() || username,
        });
      } else {
        await api.post('/api/auth/login', { username, password });
      }
      if (location.hash && location.hash !== '#/') {
        history.replaceState(null, '', '#/');
      }
      await boot();
      toastOk(isReg ? '注册成功，欢迎' : '登录成功');
    } catch (err) {
      errBox.textContent = err.message; errBox.style.display = '';
    }
  }

  const form = h('form', { class: 'panel', onsubmit: submit },
    errBox,
    h('div', { class: 'field' }, h('label', { text: '用户名' }), userIn),
    isReg ? h('div', { class: 'field' }, h('label', { text: '昵称' }), nameIn) : null,
    h('div', { class: 'field' }, h('label', { text: '密码' }), pwIn,
      isReg ? h('div', { class: 'hint', text: '至少 6 位' }) : null),
    h('button', { class: 'btn primary', type: 'submit', style: { width: '100%', marginTop: '6px' } },
      isReg ? '注册并登录' : '登录'),
  );

  // GitCode 入口：只有服务端配了凭据才显示
  const oauthBox = h('div', { class: 'oauthbox' });
  api.get('/api/auth/gitcode/status').then((d) => {
    if (!d || !d.enabled) return;
    setChildren(oauthBox, 
      h('div', { class: 'orline' }, h('span', { text: '或' })),
      h('a', { class: 'btn oauth', href: '/api/auth/gitcode/start' },
        icon('gitbranch'), '使用 GitCode 登录'),
      h('div', { class: 'hint', style: { textAlign: 'center', marginTop: '8px' },
        text: '首次登录会自动创建账号' }));
  }).catch(() => { /* 没配就当没这功能 */ });

  return h('div', { class: 'authwrap' },
    h('div', { class: 'authcard' },
      h('div', { class: 'authlogo' },
        h('span', { class: 'mark', text: 'M' }),
        h('span', { class: 'nm', text: 'MagicLink' })),
      form,
      oauthBox,
      h('div', { class: 'authswitch' },
        isReg ? '已有账号？' : '还没有账号？',
        h('button', {
          type: 'button',
          onclick: () => { clearAuthError(); go(isReg ? '/login' : '/register'); },
        }, isReg ? '去登录' : '注册一个')),
      // 首页现在是链接广场，这里给个回得去的入口
      h('div', { class: 'authback' },
        h('a', { href: '/' }, '← 链接广场'))));
}

// ── 工作台 ──────────────────────────────────────────────────────────────────
async function dashboardView() {
  let personal = { total: 0, shared: 0, pub: 0 };
  try {
    const d = await api.get('/api/local/links', { page_size: 1 });
    personal.total = d.total;
  } catch { /* ignore */ }
  try {
    const all = await api.get('/api/local/links', { page_size: 500 });
    personal.shared = all.items.filter((i) => (i.shares || []).length > 0).length;
    personal.pub = all.items.filter((i) => i.public_show).length;
  } catch { /* ignore */ }

  const stats = h('div', { class: 'statgrid' },
    h('div', { class: 'stat' }, h('div', { class: 'n', text: String(personal.total) }),
      h('div', { class: 'l', text: '我的链接' })),
    h('div', { class: 'stat' }, h('div', { class: 'n', text: String(personal.shared) }),
      h('div', { class: 'l', text: '在团队列表里' })),
    h('div', { class: 'stat' }, h('div', { class: 'n', text: String(personal.pub) }),
      h('div', { class: 'l', text: '对外公开' })),
    h('div', { class: 'stat' }, h('div', { class: 'n', text: String(state.teams.length) }),
      h('div', { class: 'l', text: '加入的团队' })),
  );

  const teamCards = state.teams.map((t) =>
    h('a', { class: 'teamcard', href: `#/team/${t.id}` },
      h('div', { class: 'name' },
        t.name,
        t.role === 'owner' ? h('span', { class: 'pill accent', text: '拥有者' }) : null),
      h('div', { class: 'meta', text: `${t.member_count} 位成员 · ${t.link_count + t.shared_count} 条链接` })));

  const body = h('div', null,
    stats,
    h('div', { class: 'side-label', style: { padding: '0', marginTop: '28px' }, text: '团队' }),
    teamCards.length
      ? h('div', { class: 'teamgrid' }, teamCards)
      : h('div', { class: 'empty' },
          h('div', { class: 't', text: '还没有团队' }),
          h('div', { text: '创建一个团队，或用邀请码加入别人的团队。' }),
          h('div', { style: { marginTop: '16px', display: 'flex', gap: '8px', justifyContent: 'center' } },
            h('button', { class: 'btn primary', onclick: () => promptCreateTeam() },
              icon('plus'), '创建团队'),
            h('button', { class: 'btn', onclick: () => promptJoinTeam() }, '用邀请码加入'))),
  );

  return layout({
    active: 'home', title: '工作台',
    sub: `欢迎回来，${state.me.display_name}`,
    actions: [
      h('button', { class: 'btn primary', onclick: () => go('/space') },
        icon('link'), '我的空间'),
    ],
    body,
  });
}

// ── 设置 ────────────────────────────────────────────────────────────────────
async function settingsView() {
  const u = state.me;
  const nameIn = h('input', { class: 'input', value: u.display_name });
  const oldPw = h('input', { class: 'input', type: 'password', placeholder: '当前密码' });
  const newPw = h('input', { class: 'input', type: 'password', placeholder: '新密码（至少 6 位）' });

  // 对外公开页：总开关 + 地址（地址就是 /u/<用户名>）
  function publicCard() {
    const enabled = !!u.public_enabled;
    const url = `${location.origin}/u/${u.username}`;
    return h('div', { class: 'card pad' },
      h('div', { style: { fontWeight: '600', marginBottom: '6px' }, text: '对外公开页' }),
      h('div', { class: 'small muted', style: { marginBottom: '14px' },
        text: enabled
          ? '已开启。你标记了「对外公开」的链接会汇总到下面这个地址，不需要登录就能访问。'
          : '关闭中。开启后，你标记了「对外公开」的链接会汇总到一个不需要登录的页面上。' }),
      enabled
        ? h('div', { class: 'field' }, h('label', { text: '地址' }),
            h('div', { class: 'inline' },
              h('span', { class: 'codechip', text: url }),
              h('button', {
                class: 'btn sm',
                onclick: async () => {
                  try { await navigator.clipboard.writeText(url); toastOk('地址已复制'); }
                  catch { toastErr('复制失败'); }
                },
              }, '复制'),
              h('a', { class: 'btn sm', href: url, target: '_blank', rel: 'noopener' },
                '打开', icon('external'))))
        : null,
      h('div', { class: 'inline', style: { marginTop: '4px' } },
        h('button', {
          class: enabled ? 'btn' : 'btn primary',
          onclick: async () => {
            try {
              await api.post('/api/me/public', { enabled: !enabled });
              await loadMe();
              toastOk(enabled ? '已关闭对外公开页' : '已开启对外公开页');
              render();
            } catch (e) { toastErr(e.message); }
          },
        }, enabled ? '关闭对外公开页' : '开启对外公开页'),
        enabled ? null : h('span', { class: 'small muted',
          text: '开启后仍需逐条把链接设为「对外公开」。' })));
  }

  // GitCode 绑定：只有服务端配了凭据才有意义
  function gitcodeCard() {
    const bound = !!u.gitcode_bound;
    const canLogin = !!u.gitcode_login_enabled;
    return h('div', { class: 'card pad' },
      h('div', { style: { fontWeight: '600', marginBottom: '6px' }, text: 'GitCode 账号' }),
      h('div', { class: 'small muted', style: { marginBottom: '14px' },
        text: !canLogin
          ? '服务端还没有配置 GitCode 登录。'
          : bound
            ? '已绑定。可以直接用 GitCode 一键登录这个账号。'
            : '绑定后就能用 GitCode 一键登录，不用再输密码。' }),
      !canLogin
        ? h('div', { class: 'hint',
            text: '在 .env 里填 GITCODE_CLIENT_ID / GITCODE_CLIENT_SECRET 后即可开启。' })
        : (bound
            ? h('div', { class: 'inline' },
                h('span', { class: 'pill accent', text: '已绑定' }),
                h('button', {
                  class: 'btn sm',
                  onclick: async () => {
                    try {
                      await api.post('/api/auth/gitcode/unbind', {});
                      await loadMe(); toastOk('已解绑'); render();
                    } catch (e) { toastErr(e.message); }
                  },
                }, '解绑'))
            : h('a', { class: 'btn primary', href: '/api/auth/gitcode/start?purpose=bind' },
                icon('gitbranch'), '绑定 GitCode 账号')));
  }

  const hasPassword = !!u.has_password;

  const body = h('div', { class: 'stack', style: { maxWidth: '520px' } },
    h('div', { class: 'card pad' },
      h('div', { style: { fontWeight: '600', marginBottom: '14px' }, text: '基本资料' }),
      h('div', { class: 'field' }, h('label', { text: '用户名' }),
        h('div', { class: 'mono muted', text: u.username })),
      h('div', { class: 'field' }, h('label', { text: '昵称' }), nameIn),
      h('button', {
        class: 'btn primary',
        onclick: async () => {
          try {
            await api.patch('/api/me', { display_name: nameIn.value.trim() });
            await loadMe(); toastOk('已保存'); render();
          } catch (e) { toastErr(e.message); }
        },
      }, '保存')),
    gitcodeCard(),
    publicCard(),
    h('div', { class: 'card pad' },
      h('div', { style: { fontWeight: '600', marginBottom: '14px' },
        text: hasPassword ? '修改密码' : '设置密码' }),
      hasPassword
        ? h('div', { class: 'field' }, h('label', { text: '当前密码' }), oldPw)
        : h('div', { class: 'hint', style: { marginBottom: '14px' },
            text: '这个账号是用 GitCode 创建的，还没有密码。设置之后就能用用户名密码登录了。' }),
      h('div', { class: 'field' }, h('label', { text: '新密码' }), newPw),
      h('div', { class: 'hint', style: { marginBottom: '14px' },
        text: '忘记密码时请联系管理员在服务器上执行重置命令。' }),
      h('button', {
        class: 'btn',
        onclick: async () => {
          try {
            await api.post('/api/me/password', {
              old_password: oldPw.value, new_password: newPw.value,
            });
            oldPw.value = newPw.value = '';
            toastOk('密码已修改');
          } catch (e) { toastErr(e.message); }
        },
      }, '修改密码')),
  );

  return layout({ active: 'settings', title: '设置', sub: '账号与密码', body });
}

// ── 团队弹窗 ────────────────────────────────────────────────────────────────
export function promptCreateTeam() {
  const nameIn = h('input', { class: 'input', placeholder: '团队名称' });
  const m = modal({
    title: '创建团队',
    sub: '创建后你会成为团队拥有者，可以把邀请码发给同事。',
    body: h('div', { class: 'field' }, h('label', { text: '团队名称' }), nameIn),
    actions: [
      h('button', { class: 'btn', text: '取消', onclick: () => m.close() }),
      h('button', {
        class: 'btn primary', text: '创建',
        onclick: async () => {
          if (!nameIn.value.trim()) return toastErr('请填写团队名称');
          try {
            const t = await api.post('/api/teams', { name: nameIn.value.trim() });
            m.close(); await loadMe(); toastOk(`团队已创建，邀请码：${t.invite_code}`);
            go(`/team/${t.id}`);
          } catch (e) { toastErr(e.message); }
        },
      }),
    ],
  });
}

// 加入 / 创建团队走同一个入口（侧边栏那一条），所以弹窗也得是这个结构：
// 默认是「填邀请码加入」，创建走下面那条文字链，另外给一个正经的「取消」。
// 之前把「创建团队」当成次要按钮摆在「加入」左边，结果既没有取消、
// 标题又只写「加入团队」，和入口名对不上。
export function promptJoinTeam() {
  const codeIn = h('input', { class: 'input mono',
                              placeholder: '10 位字母数字',
                              style: { letterSpacing: '.08em', textTransform: 'uppercase' } });
  const m = modal({
    title: '加入或创建团队',
    sub: '有邀请码就直接加入；没有的话先建一个自己的团队。',
    body: h('div', null,
      h('div', { class: 'field' },
        h('label', { text: '邀请码' }), codeIn,
        h('div', { class: 'hint', text: '向团队拥有者索取。' })),
      h('div', { class: 'altpath' },
        '没有邀请码？',
        h('a', {
          href: '#',
          onclick: (e) => { e.preventDefault(); m.close(); promptCreateTeam(); },
        }, '创建一个自己的团队'))),
    actions: [
      h('button', { class: 'btn', text: '取消', onclick: () => m.close() }),
      h('button', {
        class: 'btn primary', text: '加入',
        onclick: async () => {
          const code = codeIn.value.trim();
          if (!code) return toastErr('请填写邀请码');
          try {
            const t = await api.post('/api/teams/join', { invite_code: code });
            m.close(); await loadMe();
            // 别对早就在的团队说「已加入」
            if (t.already_member) toastOk(`你已经在「${t.name}」里了`);
            else toastOk(`已加入「${t.name}」`);
            go(`/team/${t.id}`);
          } catch (e) { toastErr(e.message); }
        },
      }),
    ],
  });
}

export function promptNewGroup(defaultName = '', onDone = null) {
  const nameIn = h('input', { class: 'input', placeholder: '分组名称', value: defaultName });
  const m = modal({
    title: '新建分组',
    body: h('div', { class: 'field' }, h('label', { text: '名称' }), nameIn),
    actions: [
      h('button', { class: 'btn', text: '取消', onclick: () => m.close() }),
      h('button', {
        class: 'btn primary', text: '创建',
        onclick: async () => {
          const name = nameIn.value.trim();
          if (!name) return toastErr('请填写分组名称');
          try {
            const g = await api.post('/api/local/groups', { name });
            m.close(); await loadGroups(); toastOk('分组已创建');
            onDone ? onDone(g) : go(`/space?g=${g.id}`);
          } catch (e) { toastErr(e.message); }
        },
      }),
    ],
  });
}

// ── 一次性 URL 标记（GitCode 回调带的）───────────────────────────────────────
// 必须在这里就消费掉并清掉 URL：登录页会被渲染多次，且刷新页面不该再弹一次。
let _pendingAuthError = '';
let _pendingBound = false;

(function consumeUrlFlags() {
  const sp = new URLSearchParams(location.search);
  _pendingAuthError = sp.get('auth_error') || '';
  _pendingBound = sp.get('bound') === '1';
  if (!_pendingAuthError && !_pendingBound) return;
  sp.delete('auth_error');
  sp.delete('bound');
  const rest = sp.toString();
  history.replaceState(null, '', location.pathname + (rest ? `?${rest}` : '') + location.hash);
})();

export function peekAuthError() {
  return _pendingAuthError;
}

export function clearAuthError() {
  _pendingAuthError = '';
}

// ── 渲染 ────────────────────────────────────────────────────────────────────
let rendering = false;
let pending = false;

export async function render() {
  if (rendering) { pending = true; return; }
  rendering = true;
  const { seg, q } = parseHash();
  const root = appEl();
  try {
    let view;
    if (!state.me) {
      const mode = seg[0] === 'register' ? 'register' : 'login';
      view = loginView(mode);
    } else if (seg[0] === 'login' || seg[0] === 'register') {
      // 已登录却访问登录页：直接进工作台，并顺手修正地址
      history.replaceState(null, '', '#/');
      view = await dashboardView();
    } else if (seg.length === 0) {
      view = await dashboardView();
    } else if (seg[0] === 'space') {
      view = await renderPersonalSpace(q);
    } else if (seg[0] === 'team' && seg[1]) {
      view = await renderTeamSpace(Number(seg[1]), q);
    } else if (seg[0] === 'settings') {
      view = await settingsView();
    } else {
      view = await dashboardView();
    }
    clear(root);
    root.append(view);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) { state.me = null; }
    clear(root);
    root.append(h('div', { class: 'wrap' },
      h('div', { class: 'empty' },
        h('div', { class: 't', text: '出错了' }),
        h('div', { text: err.message || String(err) }),
        h('button', { class: 'btn', onclick: () => { location.hash = '#/'; render(); } }, '回到工作台'))));
  } finally {
    rendering = false;
    if (pending) { pending = false; render(); }
  }
}

async function boot() {
  await refreshSidebars();
  // 已登录时（例如绑定 GitCode 失败）用 toast 说明原因；
  // 未登录时留给登录页显示。
  if (_pendingAuthError && state.me) {
    const err = peekAuthError();
    clearAuthError();
    toastErr(err);
  }
  await render();
  if (_pendingBound) {
    _pendingBound = false;
    toastOk('GitCode 绑定成功');
  }
}

onUnauthorized(() => { state.me = null; render(); });
window.addEventListener('hashchange', () => render());

boot();
