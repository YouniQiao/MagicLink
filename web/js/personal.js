import { api } from './api.js';
import {
  h,
  icon,
  toastOk,
  toastErr,
  modal,
  confirmDialog,
  hostOf,
  debounce,
  setChildren,
} from './ui.js';
import { state, layout, go, loadGroups, loadMe, promptNewGroup, publicLink } from './app.js';
import { appCard, buildSpace } from './space.js';

// ── 链接表单（个人 / 团队通用）──────────────────────────────────────────────
// 两段式：上「链接信息」，下「链接可见性」。可见性不再单独开一个弹窗——
// 一条链接会出现在哪些地方，就在建它/改它的地方一次说完。
// 标签已经没有入口，界面上也不再显示；编辑时不提交这个字段，已有数据不会被抹掉。
export async function openLinkForm({ title, link = null, groups = [], groupId = null,
                                     teamId = null, publicHint = '', onSaved }) {
  const isEdit = !!link;
  let favicon = link?.favicon || '';

  // ── 第一部分：链接信息 ──
  const urlIn = h('input', { class: 'input', placeholder: 'https://…', value: link?.url || '' });
  const titleIn = h('input', { class: 'input', placeholder: '标题', value: link?.title || '' });
  const descIn = h('textarea', { class: 'textarea', placeholder: '备注（可选）' });
  descIn.value = link?.description || '';
  const groupSel = h('select', { class: 'select' },
    h('option', { value: '', text: '未分组' }),
    ...groups.map((g) => h('option', { value: String(g.id), text: g.name })));
  const initialGroup = groupId ?? link?.group_id ?? '';
  groupSel.value = initialGroup ? String(initialGroup) : '';

  const hint = h('div', { class: 'hint', text: '填好链接后会自动抓取标题和图标。' });
  let fetching = false;

  async function autofill() {
    const raw = urlIn.value.trim();
    if (!raw || fetching) return;
    fetching = true;
    hint.textContent = '正在抓取…';
    try {
      const d = await api.post('/api/meta/fetch', { url: raw });
      if (d.ok && d.title && !titleIn.value.trim()) titleIn.value = d.title;
      if (d.description && !descIn.value.trim()) descIn.value = d.description;
      if (d.favicon) favicon = d.favicon;
      hint.textContent = d.ok ? '已自动填充标题和图标' : (d.error || '抓取失败，请手动填写');
    } catch {
      hint.textContent = '抓取失败，请手动填写';
    } finally {
      fetching = false;
    }
  }
  urlIn.addEventListener('blur', autofill);
  urlIn.addEventListener('input', debounce(() => { if (!isEdit) autofill(); }, 800));

  // ── 第二部分：链接可见性 ──
  const pubCb = h('input', { type: 'checkbox' });
  let visBlocks = [];
  let afterSave = null;    // 存完链接才能做的事（团队列表要拿到 link id）

  if (teamId) {
    // 团队链接只有一个开关。新建时默认勾上：团队空间是给团队看的，
    // 链接建完还要记得去勾一次公开，这一步没有意义。
    pubCb.checked = isEdit ? !!link.public_show : true;
    visBlocks = [h('div', { class: 'visblock' },
      h('div', { class: 'vishead' }, icon('external'), '对外公开页'),
      h('label', { class: 'check' }, pubCb,
        h('span', { text: '出现在对外公开页（不需要登录，任何人凭网址可看）' })),
      publicHint ? h('div', { class: 'hint', style: { marginLeft: '24px' } },
        publicHint) : null)];
  } else {
    // 新建时默认勾上「任何人都能看」：个人收藏默认就是给人看的，
    // 建完再回来勾一次是多余的；不想公开的取消勾选即可（总开关没开时下面会提示）。
    pubCb.checked = isEdit ? !!link.public_show : true;

    // shares 决定「团队链接列表」里哪些勾是选中的。个人空间拿到的列表里带这个字段，
    // 团队空间拿到的链接不带——那种情况下必须补拉一次，否则保存时会把
    // 已有的团队列表记录当成「没勾」而删掉。
    let shares = Array.isArray(link?.shares) ? link.shares : [];
    if (isEdit && !Array.isArray(link?.shares)) {
      try { shares = (await api.get(`/api/local/links/${link.id}/shares`)).items || []; }
      catch { shares = []; }
    }
    const current = {};
    shares.forEach((s) => { current[s.team_id] = s; });

    const teamRows = [];
    await Promise.all((state.teams || []).map(async (t) => {
      let tgroups = [];
      try { tgroups = (await api.get(`/api/teams/${t.id}/groups`)).items || []; }
      catch { /* 不是成员就忽略 */ }

      const cur = current[t.id] || {};
      const cb = h('input', { type: 'checkbox' });
      cb.checked = !!cur.in_space;
      const gsel = h('select', { class: 'select', style: { maxWidth: '200px' } },
        h('option', { value: '', text: '团队内未分组' }),
        ...tgroups.map((g) => h('option', { value: String(g.id), text: g.name })));
      gsel.value = cur.team_group_id ? String(cur.team_group_id) : '';

      const gf = h('div', {
        class: 'field', style: { margin: '6px 0 0 24px', display: cb.checked ? '' : 'none' },
      }, h('label', { text: '放在团队分组' }), gsel);
      cb.addEventListener('change', () => { gf.style.display = cb.checked ? '' : 'none'; });

      teamRows.push({
        teamId: t.id, cb, gsel, existed: !!current[t.id],
        node: h('div', { class: 'visrow' },
          h('label', { class: 'check' }, cb, h('span', { text: t.name })), gf),
      });
    }));
    teamRows.sort((a, b) => a.teamId - b.teamId);

    const pubState = h('div', { class: 'hint', style: { marginLeft: '24px' } });
    function paintPubState() {
      if (state.me?.public_enabled) {
        // 用接口给的地址（可能自定义过），别自己拼 /u/<用户名>
        const u = `${location.origin}${state.me.public_url || `/u/${state.me.username}`}`;
        setChildren(pubState, '你的公开页已开启：',
          h('a', { href: u, target: '_blank', rel: 'noopener' }, u));
      } else {
        // 总开关没开时勾了也不会出现——当场说出来，别让它静默失败
        setChildren(pubState, 
          h('span', { style: { color: 'var(--warn)' },
            text: '你的公开页还没开启，勾了也不会出现。' }), ' ',
          h('button', {
            class: 'btn sm', type: 'button',
            onclick: async () => {
              try {
                await api.post('/api/me/public', { enabled: true });
                await loadMe(); paintPubState(); toastOk('已开启你的对外公开页');
              } catch (e) { toastErr(e.message); }
            },
          }, '去开启'));
      }
    }
    paintPubState();

    afterSave = async (saved) => {
      for (const r of teamRows) {
        if (!r.cb.checked) {
          if (r.existed) await api.del(`/api/local/links/${saved.id}/shares/${r.teamId}`);
          continue;
        }
        await api.put(`/api/local/links/${saved.id}/shares/${r.teamId}`, {
          in_space: true,
          team_group_id: r.gsel.value ? Number(r.gsel.value) : null,
        });
      }
    };

    visBlocks = [
      h('div', { class: 'visblock' },
        h('div', { class: 'vishead' }, icon('users'), '团队链接列表'),
        teamRows.length ? h('div', null, ...teamRows.map((r) => r.node))
          : h('div', { class: 'hint', text: '你还没有加入团队。' })),
      h('div', { class: 'visblock' },
        h('div', { class: 'vishead' }, icon('external'), '对外公开页'),
        h('label', { class: 'check' }, pubCb,
          h('span', { text: '任何人都能看（不需要登录）' })),
        pubState),
    ];
  }

  const m = modal({
    title,
    body: h('div', null,
      h('section', { class: 'formsec' },
        h('div', { class: 'formsechead' }, icon('link'), '链接信息'),
        h('div', { class: 'field' }, h('label', { text: '链接' }), urlIn,
          isEdit ? null : hint),
        h('div', { class: 'field' }, h('label', { text: '标题' }), titleIn),
        h('div', { class: 'field' }, h('label', { text: '备注' }), descIn),
        h('div', { class: 'field' }, h('label', { text: '分组' }), groupSel)),
      h('section', { class: 'formsec' },
        h('div', { class: 'formsechead' }, icon('share'), '链接可见性'),
        ...visBlocks)),
    actions: [
      h('button', { class: 'btn', text: '取消', onclick: () => m.close() }),
      h('button', {
        class: 'btn primary', text: isEdit ? '保存' : '添加',
        onclick: async () => {
          const raw = urlIn.value.trim();
          if (!raw) return toastErr('请填写链接');
          const url = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(raw) ? raw : `https://${raw}`;
          try { new URL(url); } catch { return toastErr('链接格式不正确'); }

          // 故意不带 tags：编辑时不提交这个字段，后端按「没传=不动」处理，
          // 已有标签不会被这次保存抹掉。
          const payload = {
            url,
            title: titleIn.value.trim() || hostOf(url),
            description: descIn.value.trim(),
            favicon,
            group_id: groupSel.value ? Number(groupSel.value) : null,
            clear_group: !groupSel.value,
            public_show: pubCb.checked,
          };
          const base = teamId ? `/api/teams/${teamId}/links` : '/api/local/links';
          try {
            const saved = isEdit
              ? await api.patch(`${base}/${link.id}`, payload)
              : await api.post(base, payload);
            if (afterSave) await afterSave(saved);
            m.close(); toastOk(isEdit ? '已保存' : '已添加'); onSaved?.(saved);
          } catch (e) { toastErr(e.message); }
        },
      }),
    ],
  });
}

// ── 链接卡片 ────────────────────────────────────────────────────────────────
// 版式和公开页一致（都在 space.js 的 appCard 里），这里只负责个人空间的操作集。
// 可见性已经并进「编辑」表单（链接信息 + 链接可见性），所以卡片上不再有单独的
// 可见性按钮——同一个开关只留一个入口。
//
// onCopyToPersonal 只在团队空间传：把这条团队链接复制一份到我的个人空间。
// （那条路以前只有接口没有入口，现在接上了。）
export function linkCard(item, { onEdit, onDelete, editable = true,
                                 deletable = true, badges = [],
                                 onCopyToPersonal = null } = {}) {
  const shareCount = (item.shares || []).length;
  return appCard(item, {
    badges: [
      shareCount
        // 不带小人图标：这两个字文案已经说清楚了，图标只是占宽度。
        // 而且这一行原本就卡着线（194px / 可用 197px），多两个字就会翻成两行。
        ? h('span', { class: 'pill accent' }, `在 ${shareCount} 个团队列表`)
        : null,
      item.public_show
        // 同样不带图标：文字已经说明白了
        ? h('span', { class: 'pill pub', title: '对外公开：不需要登录，任何人凭网址可看' },
            '对外公开')
        : null,
      item.copied_from_link_id
        ? h('span', { class: 'pill warn', text: '来自团队复制' }) : null,
      ...badges,
    ],
    actions: [
      editable ? { icon: 'pencil', title: '编辑', onClick: onEdit } : null,
      // 「复制链接地址」——拷 URL 到剪贴板。跟下面那个「复制到我的空间」是两件事，
      // 标题里点明「地址」，否则两个都叫「复制…」分不出来。
      { icon: 'copy', title: '复制链接地址', onClick: copyUrl },
      onCopyToPersonal
        ? { icon: 'import', title: '复制到我的空间', onClick: onCopyToPersonal } : null,
      deletable ? { icon: 'trash', title: '删除', danger: true, onClick: onDelete } : null,
    ],
  });
}

async function copyUrl(item) {
  try { await navigator.clipboard.writeText(item.url); toastOk('链接已复制'); }
  catch { toastErr('复制失败'); }
}

export function pager(d, onGo) {
  if (!d || d.pages <= 1) return null;
  return h('div', { class: 'pager' },
    h('button', { class: 'btn sm', disabled: d.page <= 1, onclick: () => onGo(d.page - 1) },
      icon('left'), '上一页'),
    h('span', { text: `第 ${d.page} / ${d.pages} 页 · 共 ${d.total} 条` }),
    h('button', { class: 'btn sm', disabled: d.page >= d.pages, onclick: () => onGo(d.page + 1) },
      '下一页', icon('right')));
}

// ── 个人空间页 ──────────────────────────────────────────────────────────────
export async function renderPersonalSpace(q) {
  const groups = state.groups;
  const params = {
    q: q.get('q') || '',
    page: Number(q.get('page') || 1),
    page_size: 500,     // 分组展示要一次拿全，不然同一个分组会被分页切开
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
    go(`/space?${nq.toString()}`);
  };

  async function newLink() {
    openLinkForm({
      title: '新建链接', groups, groupId: params.group_id || null,
      onSaved: async () => { await loadGroups(); await refresh(); },
    });
  }

  function editLink(item) {
    openLinkForm({
      title: '编辑链接', link: item, groups,
      onSaved: async () => { await loadGroups(); await refresh(); },
    });
  }

  function deleteLink(item) {
    confirmDialog({
      title: '删除链接',
      message: `确定删除「${item.title}」吗？删掉后团队里也看不到了。`,
      confirmText: '删除', danger: true,
    }).then(async (ok) => {
      if (!ok) return;
      try {
        await api.del(`/api/local/links/${item.id}`);
        toastOk('已删除'); await loadGroups(); await refresh();
      } catch (e) { toastErr(e.message); }
    });
  }

  const isFiltering = !!(params.q || params.group_id || params.ungrouped);

  function buildList(data) {
    const empty = h('div', { class: 'empty' },
      h('div', { class: 't', text: isFiltering ? '没有匹配的链接' : '这里还没有链接' }),
      h('div', { text: isFiltering ? '换个关键词试试。' : '添加第一条链接开始使用。' }),
      isFiltering ? null
        : h('button', { class: 'btn primary', onclick: newLink },
            icon('plus'), '新建链接'));

    return buildSpace({
      groups, items: data.items, isFiltering, emptyNode: empty,
      renderCard: (it) => linkCard(it, {
        onEdit: editLink,
        onDelete: deleteLink,
      }),
      reorderEntry: (it) => it.id,
      async onReorderLinks(groupId, ids) {
        try {
          await api.post('/api/local/links/reorder', { group_id: groupId, items: ids });
        } catch (e) { toastErr(e.message); await refresh(); }
      },
      async onReorderGroups(ids) {
        try {
          await api.post('/api/local/groups/reorder', { items: ids });
          await loadGroups();
        } catch (e) { toastErr(e.message); await refresh(); }
      },
    });
  }

  let current = await api.get('/api/local/links', params);

  async function refresh() {
    current = await api.get('/api/local/links', params);
    const holder = document.getElementById('space-list');
    setChildren(holder, buildList(current), pager(current, (p) => setParam({ page: p })));
  }

  const searchIn = h('input', {
    class: 'input', placeholder: '搜索标题 / 链接 / 备注', value: params.q,
  });
  searchIn.addEventListener('input', debounce(() => setParam({ q: searchIn.value.trim() })));

  const toolbar = h('div', { class: 'toolbar' },
    h('div', { class: 'search' }, icon('search'), searchIn),
    h('div', { class: 'spacer' }),
    // 位置和团队空间一致：搜索框那一行的工具栏里，「新建分组」在「新建链接」左边
    h('button', { class: 'btn sm', onclick: () => promptNewGroup() }, icon('plus'), '新建分组'),
    h('button', { class: 'btn primary', onclick: newLink }, icon('plus'), '新建链接'));

  // 分组筛选挪进页面里（和团队空间一样）：分组是空间内部的结构，
  // 不再占侧边栏的位置。点一个分组 = 只看那一组，再点一次取消。
  const groupPills = groups.length
    ? h('div', { class: 'pillbar' },
        h('button', {
          class: `pill ${!params.group_id && !params.ungrouped ? 'active' : ''}`,
          onclick: () => setParam({ g: null, ungrouped: null }),
        }, '全部分组'),
        h('button', {
          class: `pill ${params.ungrouped ? 'active' : ''}`,
          onclick: () => setParam({ ungrouped: params.ungrouped ? null : '1', g: null }),
        }, '未分组'),
        ...groups.map((g) => h('button', {
          class: `pill ${params.group_id === g.id ? 'active' : ''}`,
          onclick: () => setParam({ g: params.group_id === g.id ? null : g.id, ungrouped: null }),
        }, icon('folder', 12), `${g.name} ${g.link_count}`)))
    : null;

  const headActions = [
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
                  await api.patch(`/api/local/groups/${activeGroup.id}`, { name });
                  m.close(); await loadGroups(); go(`/space?g=${activeGroup.id}`);
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
        message: `删除「${activeGroup.name}」后，组内链接会变成未分组（链接本身不删）。`,
        confirmText: '删除分组', danger: true,
      }).then(async (ok) => {
        if (!ok) return;
        try {
          await api.del(`/api/local/groups/${activeGroup.id}`);
          toastOk('分组已删除'); await loadGroups(); go('/space');
        } catch (e) { toastErr(e.message); }
      }),
    }, '删除分组') : null,
  ].filter(Boolean);

  const sub = activeGroup ? `分组：${activeGroup.name}`
    : (params.ungrouped ? '未分组的链接' : `共 ${current.total} 条链接`);

  return layout({
    active: 'space',
    title: '我的空间',
    sub: [sub, publicLink(state.me?.public_url)],   // 没开公开页时 publicLink 返回 null，被过滤掉
    actions: headActions,
    wide: true,
    body: h('div', null, toolbar, groupPills,
      h('div', { id: 'space-list' },
        buildList(current), pager(current, (p) => setParam({ page: p })))),
  });
}
