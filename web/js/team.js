import { api } from './api.js';
import {
  h,
  icon,
  toastOk,
  toastErr,
  modal,
  confirmDialog,
  initials,
  fmtDate,
  debounce,
  setChildren,
} from './ui.js';
import { state, layout, go, loadMe, loadGroups, publicLink } from './app.js';
import { linkCard, pager, openLinkForm } from './personal.js';
import { buildSpace } from './space.js';

// ── 团队设置（拥有者）───────────────────────────────────────────────────────
function openTeamSettings(team) {
  const nameIn = h('input', { class: 'input', value: team.name });
  const codeBox = h('span', { class: 'codechip', text: team.invite_code || '—' });

  // ── 对外公开页 ──
  const slugIn = h('input', {
    class: 'input', placeholder: '例如 doc-team（留空则用 team-<编号>）',
    value: team.public_slug || '',
  });
  let pubOn = !!team.public_enabled;
  const pubState = h('div', { class: 'hint' });
  const pubBtn = h('button', { onclick: togglePublic });

  function paintPub() {
    pubBtn.textContent = pubOn ? '关闭对外公开页' : '开启对外公开页';
    pubBtn.className = pubOn ? 'btn' : 'btn primary';
    if (pubOn) {
      const url = `${location.origin}${team.public_url || `/t/team-${team.id}`}`;
      setChildren(pubState, 
        h('span', { class: 'codechip', text: url }), ' ',
        h('a', { class: 'btn sm', href: url, target: '_blank', rel: 'noopener' },
          '打开', icon('external')));
    } else {
      pubState.textContent = '未开启。团队成员标记了「对外公开」的链接现在都不会对外显示。';
    }
  }

  async function togglePublic() {
    try {
      const d = await api.post(`/api/teams/${team.id}/public`, {
        enabled: !pubOn, slug: slugIn.value.trim() || null,
      });
      pubOn = d.public_enabled;
      team.public_slug = d.public_slug;
      team.public_url = d.public_url;
      paintPub();
      toastOk(pubOn ? '已开启对外公开页' : '已关闭对外公开页');
    } catch (e) { toastErr(e.message); }
  }

  const m = modal({
    title: '团队设置',
    sub: `拥有者：你 · 成员 ${team.member_count} 人`,
    body: h('div', null,
      h('div', { class: 'field' },
        h('label', { text: '团队名称' }), nameIn,
        h('div', { class: 'hint', text: '修改后立即生效。' })),
      h('div', { class: 'field' },
        h('label', { text: '邀请码' }),
        h('div', { class: 'inline' }, codeBox,
          h('button', {
            class: 'btn sm',
            onclick: async () => {
              try { await navigator.clipboard.writeText(codeBox.textContent); toastOk('邀请码已复制'); }
              catch { toastErr('复制失败'); }
            },
          }, '复制'),
          h('button', {
            class: 'btn sm',
            onclick: () => confirmDialog({
              title: '重新生成邀请码',
              message: '旧邀请码会立即失效，已经加入的成员不受影响。',
              confirmText: '重新生成',
            }).then(async (ok) => {
              if (!ok) return;
              const d = await api.post(`/api/teams/${team.id}/invite/regenerate`);
              codeBox.textContent = d.invite_code;
              toastOk('已生成新邀请码');
            }),
          }, '重新生成'))),
      h('div', { class: 'divider' }),
      h('div', { class: 'field' },
        h('label', { text: '对外公开页' }),
        h('div', { class: 'small muted', style: { marginBottom: '8px' },
          text: '开启后，团队里标记了「对外公开」的链接会汇总到一个不需要登录的页面。地址可读，知道网址的人都能访问。' }),
        h('div', { class: 'field' }, h('label', { text: '地址' }), slugIn),
        h('div', { class: 'inline' }, pubBtn),
        h('div', { style: { marginTop: '10px' } }, pubState)),
      h('div', { class: 'divider' }),
      h('div', { class: 'inline' },
        h('div', { class: 'small muted', text: '删除团队会移除团队链接与共享关系（个人链接不受影响）。' }),
        h('div', { class: 'spacer' }),
        h('button', {
          class: 'btn danger',
          onclick: () => confirmDialog({
            title: `删除团队「${team.name}」`,
            message: '此操作不可撤销。',
            confirmText: '确认删除', danger: true,
          }).then(async (ok) => {
            if (!ok) return;
            await api.del(`/api/teams/${team.id}`);
            m.close(); await loadMe(); toastOk('团队已删除'); go('/');
          }),
        }, '删除团队'))),
    actions: [
      h('button', { class: 'btn', text: '关闭', onclick: () => m.close() }),
      h('button', {
        class: 'btn primary', text: '保存名称',
        onclick: async () => {
          try {
            await api.patch(`/api/teams/${team.id}`, { name: nameIn.value.trim() });
            m.close(); await loadMe(); toastOk('已保存'); go(`/team/${team.id}`);
          } catch (e) { toastErr(e.message); }
        },
      }),
    ],
  });
  paintPub();
}

// ── 成员面板 ────────────────────────────────────────────────────────────────
async function membersPanel(teamId, team) {
  const data = await api.get(`/api/teams/${teamId}/members`);

  const rows = data.items.map((mm) => {
    const right = h('div', { class: 'right' },
      h('span', { class: 'small muted', text: `贡献 ${mm.contributed_count} 条团队链接` }));

    if (team.my_role === 'owner' && mm.role !== 'owner') {
      right.append(h('button', {
        class: 'btn sm danger',
        onclick: () => confirmDialog({
          title: `移除 ${mm.display_name || mm.username}`,
          message: '该成员将失去本团队的访问权限。',
          confirmText: '移除', danger: true,
        }).then(async (ok) => {
          if (!ok) return;
          await api.del(`/api/teams/${teamId}/members/${mm.id}`);
          toastOk('已移除');
          go(`/team/${teamId}?view=members`);
        }),
      }, '移除'));
    }

    return h('div', { class: 'memberrow' },
      h('span', { class: 'avatar', text: initials(mm.display_name) }),
      h('div', null,
        h('div', { class: 'nm' },
          mm.display_name || mm.username,
          mm.role === 'owner'
            ? h('span', { class: 'pill accent', style: { marginLeft: '8px' }, text: '拥有者' })
            : null),
        h('div', { class: 'sub', text: `@${mm.username} · 加入于 ${fmtDate(mm.joined_at)}` })),
      right);
  });

  return h('div', { class: 'card pad' },
    h('div', { class: 'inline', style: { marginBottom: '6px' } },
      h('div', { style: { fontWeight: '600' }, text: '团队成员' }),
      h('div', { class: 'spacer' }),
      h('span', { class: 'small muted', text: `${data.items.length} 人` })),
    ...rows);
}

// ── 团队空间页 ──────────────────────────────────────────────────────────────
export async function renderTeamSpace(teamId, q) {
  const team = await api.get(`/api/teams/${teamId}`);
  const view = q.get('view') === 'members' ? 'members' : 'links';

  const actions = [
    h('button', {
      class: view === 'members' ? 'btn sm primary' : 'btn sm',
      onclick: () => go(view === 'members' ? `/team/${teamId}` : `/team/${teamId}?view=members`),
    }, icon('users'), view === 'members' ? '返回链接' : '成员'),
    team.my_role === 'owner'
      ? h('button', { class: 'btn sm', onclick: () => openTeamSettings(team) }, icon('settings'), '设置')
      : null,
  ].filter(Boolean);

  if (view === 'members') {
    return layout({
      active: `t${teamId}`,
      title: team.name,
      sub: [`${team.member_count} 位成员 · ${team.link_count} 条团队链接 · ${team.shared_count} 条成员共享`,
            publicLink(team.public_url)],
      actions,
      body: await membersPanel(teamId, team),
    });
  }

  const groups = await api.get(`/api/teams/${teamId}/groups`).then((d) => d.items || []);
  const params = {
    q: q.get('q') || '',
    page: Number(q.get('page') || 1),
    page_size: 500,    // 分组展示要一次拿全，不然同一个分组会被分页切开
  };
  if (q.get('ungrouped')) params.ungrouped = true;
  else if (q.get('g')) params.group_id = Number(q.get('g'));
  const activeGroup = params.group_id ? groups.find((g) => g.id === params.group_id) : null;

  const setParam = (patch) => {
    const nq = new URLSearchParams(q.toString());
    Object.entries(patch).forEach(([k, v]) => {
      if (v === null || v === '' || v === undefined) nq.delete(k); else nq.set(k, v);
    });
    if (!('page' in patch)) nq.delete('page');
    go(`/team/${teamId}?${nq.toString()}`);
  };

  let current = await api.get(`/api/teams/${teamId}/links`, params);

  async function refresh() {
    current = await api.get(`/api/teams/${teamId}/links`, params);
    const holder = document.getElementById('team-list');
    setChildren(holder, buildList(current), pager(current, (p) => setParam({ page: p })));
  }

  function newTeamLink() {
    openLinkForm({
      title: '新建团队链接', groups, groupId: params.group_id || null, teamId,
      publicHint: teamPublicHint,   // 默认勾了公开，就更要说清总开关开没开
      onSaved: async () => { await refresh(); },
    });
  }

  const isFiltering = !!(params.q || params.group_id || params.ungrouped);

  // 团队链接的公开开关要知道团队公开页开没开，否则勾了也不生效
  const teamPublicHint = team.public_enabled
    ? `团队公开页已开启：${location.origin}${team.public_url || ''}`
    : '⚠ 团队公开页还没开启，勾了也不会出现。拥有者可去「设置」里开启。';

  // ── 把团队里的链接复制一份到我的个人空间 ──────────────────────────────────
  // 跟「共享」不是一回事：共享是引用同一份（内容归本人维护，团队改了跟着变），
  // 复制出来的**独立副本**归你、随便改，之后团队那边再改这份不会跟着动。
  // 这个接口原先只有后端、没有入口，卡片上那个「来自团队复制」徽标因此永不出现。
  async function openCopyToPersonal(it) {
    // 个人分组要现拉：团队页只加载了团队分组，两边 id 空间不同，绝不能混用。
    let myGroups = [];
    try { myGroups = (await api.get('/api/local/groups')).items || []; }
    catch { /* 拉不到就只给「未分组」 */ }

    const gsel = h('select', { class: 'select' },
      h('option', { value: '', text: '未分组' }),
      ...myGroups.map((g) => h('option', { value: String(g.id), text: g.name })));

    const m = modal({
      title: '复制到我的空间',
      sub: it.title || it.url,
      body: h('div', null,
        h('div', { class: 'field' }, h('label', { text: '放进哪个分组' }), gsel),
        h('div', { class: 'hint',
          text: '独立副本，归你所有、可随意改；团队那边之后再改，这份不会跟着变。' })),
      actions: [
        h('button', { class: 'btn', text: '取消', onclick: () => m.close() }),
        h('button', {
          class: 'btn primary', text: '复制',
          onclick: async () => {
            try {
              await api.post(`/api/teams/${teamId}/links/${it.id}/copy-to-personal`,
                             { group_id: gsel.value ? Number(gsel.value) : null });
              m.close();
              toastOk('已复制到我的空间');
            } catch (e) { toastErr(e.message); }
          },
        }),
      ],
    });
  }

  function teamCard(it) {
    const isShared = it.kind === 'shared';
    const owned = it.owner_id === state.me.id;

    // 两种来源都要能看出「谁加的」：
    //  · shared = 成员从自己个人空间放进来的（内容归本人维护，团队这边只是引用）
    //  · team   = 直接在团队空间里加的（内容归团队）
    const badges = [];
    if (isShared) {
      badges.push(h('span', {
        class: 'pill accent',
        title: '来自成员个人空间：引用同一份，内容由本人维护',
      }, icon('users', 12), `来自 ${it.owner_name}`));
    } else if (it.owner_name) {
      badges.push(h('span', {
        class: 'pill',
        title: '这条链接是在团队空间里添加的（内容归团队）',
      }, icon('user', 12), `由 ${owned ? '我' : it.owner_name} 添加`));
    }

    return linkCard(it, {
      badges,
      editable: it.can_edit,
      deletable: it.can_remove,
      onCopyToPersonal: (item) => openCopyToPersonal(item),
      onEdit: (item) => {
        if (isShared && owned) {
          openLinkForm({
            title: '编辑个人链接（内容改动团队同步可见）',
            link: item, groups: state.groups, teamId: null,
            onSaved: async () => { await loadGroups(); await refresh(); },
          });
        } else {
          openLinkForm({
            title: '编辑团队链接', link: item, groups, groupId: null, teamId,
            publicHint: teamPublicHint,
            onSaved: async () => { await refresh(); },
          });
        }
      },
      onDelete: (item) => {
        confirmDialog({
          title: isShared ? '从团队空间移除' : '删除团队链接',
          message: isShared
            ? '移除后该链接不再出现在团队空间，链接本身仍在该成员的个人空间里。'
            : `确定删除「${item.title}」吗？`,
          confirmText: isShared ? '移除' : '删除', danger: true,
        }).then(async (ok) => {
          if (!ok) return;
          try {
            await api.del(`/api/teams/${teamId}/links/${item.id}`);
            toastOk(isShared ? '已移出团队空间' : '已删除');
            await refresh();
          } catch (e) { toastErr(e.message); }
        });
      },
    });
  }

  function buildList(data) {
    const empty = h('div', { class: 'empty' },
      h('div', { class: 't', text: isFiltering ? '没有匹配的链接' : '团队空间还没有链接' }),
      h('div', { text: isFiltering
        ? '换个关键词试试。'
        : '添加团队链接，或让成员把自己的个人链接放进团队列表。' }),
      isFiltering ? null
        : h('button', { class: 'btn primary', onclick: newTeamLink }, icon('plus'), '新建团队链接'));

    return buildSpace({
      groups, items: data.items, isFiltering, emptyNode: empty,
      renderCard: teamCard,
      reorderEntry: (it) => ({ kind: it.kind, id: it.id }),
      async onReorderLinks(groupId, entries) {
        try {
          await api.post(`/api/teams/${teamId}/links/reorder`,
                         { group_id: groupId, items: entries });
        } catch (e) { toastErr(e.message); await refresh(); }
      },
      async onReorderGroups(ids) {
        try {
          await api.post(`/api/teams/${teamId}/groups/reorder`, { items: ids });
          await loadGroups();
        } catch (e) { toastErr(e.message); await refresh(); }
      },
    });
  }

  const searchIn = h('input', {
    class: 'input', placeholder: '搜索团队链接', value: params.q,
  });
  searchIn.addEventListener('input', debounce(() => setParam({ q: searchIn.value.trim() })));

  const groupPills = groups.length
    ? h('div', { class: 'pillbar' },
        h('button', {
          class: `pill ${!params.group_id && !params.ungrouped ? 'active' : ''}`,
          onclick: () => setParam({ g: null, ungrouped: null }),
        }, '全部'),
        h('button', {
          class: `pill ${params.ungrouped ? 'active' : ''}`,
          onclick: () => setParam({ ungrouped: params.ungrouped ? null : '1', g: null }),
        }, '未分组'),
        ...groups.map((g) => h('button', {
          class: `pill ${params.group_id === g.id ? 'active' : ''}`,
          onclick: () => setParam({ g: params.group_id === g.id ? null : g.id, ungrouped: null }),
        }, icon('folder', 12), `${g.name} ${g.link_count}`)))
    : null;

  function newGroup() {
    const nameIn = h('input', { class: 'input', placeholder: '分组名称' });
    const m = modal({
      title: '新建团队分组',
      body: h('div', { class: 'field' }, h('label', { text: '名称' }), nameIn),
      actions: [
        h('button', { class: 'btn', text: '取消', onclick: () => m.close() }),
        h('button', {
          class: 'btn primary', text: '创建',
          onclick: async () => {
            if (!nameIn.value.trim()) return toastErr('请填写分组名称');
            try {
              await api.post(`/api/teams/${teamId}/groups`, { name: nameIn.value.trim() });
              m.close(); toastOk('分组已创建'); go(`/team/${teamId}`);
            } catch (e) { toastErr(e.message); }
          },
        }),
      ],
    });
  }

  const toolbar = h('div', { class: 'toolbar' },
    h('div', { class: 'search' }, icon('search'), searchIn),
    h('div', { class: 'spacer' }),
    h('button', { class: 'btn sm', onclick: newGroup }, icon('plus'), '新建分组'),
    h('button', { class: 'btn primary', onclick: newTeamLink }, icon('plus'), '新建团队链接'));

  const headActions = [
    ...actions,
    // 重命名 / 删除分组。顺序跟个人空间那边一致（先重命名、后删除）。
    activeGroup ? h('button', {
      class: 'btn sm',
      onclick: () => {
        const nameIn = h('input', { class: 'input', value: activeGroup.name });
        const m = modal({
          title: '重命名分组',
          body: h('div', { class: 'field' }, h('label', { text: '名称' }), nameIn),
          actions: [
            h('button', { class: 'btn', text: '取消', onclick: () => m.close() }),
            h('button', {
              class: 'btn primary', text: '保存',
              onclick: async () => {
                // 后端不拦空名字（传空白会真的把组名写成空），这里拦一道
                const name = nameIn.value.trim();
                if (!name) return toastErr('请填写分组名称');
                try {
                  await api.patch(`/api/teams/${teamId}/groups/${activeGroup.id}`, { name });
                  m.close(); toastOk('分组已重命名');
                  // 回到同一个分组：渲染时会重新拉一次团队分组，新名字就生效了
                  go(`/team/${teamId}?g=${activeGroup.id}`);
                } catch (e) { toastErr(e.message); }
              },
            }),
          ],
        });
      },
    }, '重命名分组') : null,
    activeGroup ? h('button', {
      class: 'btn sm danger',
      onclick: () => confirmDialog({
        title: '删除分组',
        message: `删除「${activeGroup.name}」后组内链接变为未分组。`,
        confirmText: '删除分组', danger: true,
      }).then(async (ok) => {
        if (!ok) return;
        try {
          await api.del(`/api/teams/${teamId}/groups/${activeGroup.id}`);
          toastOk('分组已删除'); go(`/team/${teamId}`);
        } catch (e) { toastErr(e.message); }
      }),
    }, '删除分组') : null,
  ].filter(Boolean);

  return layout({
    active: `t${teamId}`,
    title: team.name,
    sub: [`${team.member_count} 位成员 · ${team.link_count} 条团队链接 · ${team.shared_count} 条成员共享`,
          publicLink(team.public_url)],
    actions: headActions,
    wide: true,
    body: h('div', null, toolbar, groupPills,
      h('div', { id: 'team-list' },
        buildList(current), pager(current, (p) => setParam({ page: p })))),
  });
}

// ── 成员个人空间（已下线）───────────────────────────────────────────────────
// 注：「成员个人空间页」视图（renderMemberProfile）已随该功能下线。
// 对外展示用公开页（/u/、/t/），团队内不再互相浏览收藏。
