// 空间视图：个人空间 / 团队空间共用的一套展示。
//
// 两件事：
//   1. 按分组归类链接卡片，网格用和公开页同一套列规则（宽屏一行 4 个）。
//   2. 拖拽排序——卡片在自己所在分组里挪，分组标题在整个列表里挪。
//
// 顺序存的是 position，公开页读的是同一份数据，所以这里拖完，公开页跟着变。
// 用原生 HTML5 拖拽实现，不引第三方库。
import { h, icon, hostOf, fmtDate } from './ui.js';

// 从按钮/链接/输入框上起拖不算拖拽：否则点「删除」时手一抖就把卡片拖走了。
const PRESSABLE = 'button, a, input, select, textarea, label';

let _pressOnWidget = false;
let _dragCard = null;      // 正在拖的卡片
let _dragGrid = null;      // 它所在的分组网格（跨分组不放行）
let _dragSection = null;   // 正在拖的分组
let _origOrder = null;     // 拖之前的顺序，拖拽被取消（Esc）时用来还原
let _dropped = false;      // 落在过有效目标上（dragover 里置位）
let _committed = false;    // 已经提交过了，避免 drop + dragend 提交两次

document.addEventListener('mousedown', (e) => {
  _pressOnWidget = !!(e.target.closest && e.target.closest(PRESSABLE));
}, true);

// 注意必须是冒泡阶段（不能传 true）：捕获阶段会在容器自己的 dragend 之前先跑，
// 把状态清干净，于是提交那一步永远看不到 _dropped，拖拽就白拖了。
document.addEventListener('dragend', () => {
  // dragend 一定在 drop 之后触发。没落到任何有效目标上（比如按了 Esc）
  // 就把 DOM 还原回拖之前的样子，别留下一个「看起来改了其实没存」的假象。
  if (!_dropped && _origOrder) restoreOrder();
  resetDrag();
});

function restoreOrder() {
  _origOrder.forEach(({ parent, el }) => parent.appendChild(el));
}

function resetDrag() {
  _dragCard?.classList.remove('dragging');
  _dragSection?.classList.remove('dragging');
  _dragCard = _dragGrid = _dragSection = null;
  _origOrder = null;
  _dropped = false;
  _committed = false;
}


// ── 链接卡片 ────────────────────────────────────────────────────────────────
// 版式跟公开页的 .pubcard 一致（同样的留白、图标框、标题字号），
// 管理界面需要操作入口，所以在底部多一行：左边拖拽把手，右边操作按钮。
export function appCard(item, opts = {}) {
  const { badges = [], actions = [], ownerName = '' } = opts;

  const fav = h('div', { class: 'favbox' });
  if (item.favicon) {
    const img = h('img', { src: item.favicon, alt: '', loading: 'lazy',
                           referrerpolicy: 'no-referrer' });
    img.addEventListener('error', () => {
      img.remove(); fav.append(icon('link', 16, 'fallback'));
    });
    fav.append(img);
  } else {
    fav.append(icon('link', 16, 'fallback'));
  }

  // 不显示域名（标题本身就是超链接）、也不显示标签（标签已没有入口，界面统一不展示）
  const meta = h('div', { class: 'pubmeta' }, ...badges.filter(Boolean));

  const title = h('div', { class: 'pubtitle' },
    h('a', { href: item.url, target: '_blank', rel: 'noopener noreferrer' },
      h('span', { class: 'label', text: item.title || hostOf(item.url) })),
    icon('external', 13));

  const btns = [];
  actions.forEach((a) => {
    if (!a) return;
    btns.push(h('button', {
      class: `iconbtn${a.danger ? ' danger' : ''}`, title: a.title,
      onclick: (e) => { e.stopPropagation(); a.onClick(item); },
    }, icon(a.icon)));
  });
  // 这里原先还有一个「可见性」快捷按钮（onVisibility / visibilityTitle）。
  // 可见性后来并进了链接的编辑表单，卡片上那个按钮就没人再传参了 ——
  // 参数和渲染分支一起删掉，别留一段永远不执行的代码。

  const foot = h('div', { class: 'cardfoot' },
    h('span', { class: 'grip', title: '拖动调整位置' }, icon('grip', 14)),
    h('span', { class: 'small muted carddate', text: fmtDate(item.updated_at) }),
    h('div', { class: 'linkactions' }, ...btns));

  return h('div', { class: 'appcard' , title: item.description || item.title || item.url },
    h('div', { class: 'appcard-main' },
      fav,
      h('div', { class: 'pubmain' },
        title,
        item.description ? h('div', { class: 'pubdesc', text: item.description }) : null,
        ownerName ? h('div', { class: 'pubmeta' },
          h('span', { class: 'pill accent' }, icon('users', 12), `来自 ${ownerName}`)) : null,
        meta)),
    foot);
}


// ── 分组网格 + 拖拽 ─────────────────────────────────────────────────────────

/** 找出「拖到哪张卡前面」（返回 null 表示放到最后）。 */
function cardRef(grid, x, y, dragging) {
  const cards = [...grid.children].filter(
    (el) => el.classList.contains('appcard') && el !== dragging);
  for (const c of cards) {
    const r = c.getBoundingClientRect();
    // 网格是多行的：先看纵向过没过中线，再在同一行里看横向。
    const after = (y > r.top + r.height / 2) ||
                  (y > r.top && x > r.left + r.width / 2);
    if (!after) return c;
  }
  return null;
}

function sectionRef(container, y, dragging) {
  const secs = [...container.children].filter(
    (el) => el.classList.contains('groupsec') && el !== dragging &&
           el.dataset.gid !== '');           // 「未分组」永远排最后，不参与排序
  for (const s of secs) {
    const r = s.getBoundingClientRect();
    if (y < r.top + r.height / 2) return s;
  }
  // 拖到最后：插在「未分组」前面，别越过它——越过也会被刷新还原
  const tail = [...container.children].find(
    (el) => el.classList.contains('groupsec') && el !== dragging && el.dataset.gid === '');
  return tail || null;
}

/**
 * 建出「分组 → 卡片网格」的整块内容，并挂上拖拽。
 *
 * @param {object} o
 * @param {Array}  o.groups      分组列表（已按 position 排好）
 * @param {Array}  o.items       链接（已按分组/位置排好）
 * @param {Function} o.renderCard   (item) => 卡片元素，默认用 appCard
 * @param {Function} o.reorderEntry (item) => 提交给重排接口的条目
 * @param {Function} o.onReorderLinks  (groupId, entries) => Promise
 * @param {Function} o.onReorderGroups (groupIds) => Promise
 * @param {boolean}  o.isFiltering  正在搜索/筛选（空分组就不显示了）
 * @param {boolean}  o.canReorder  允许拖拽排序
 * @param {Node}     o.emptyNode    一条链接都没有时显示什么
 */
export function buildSpace(o) {
  const {
    groups = [], items = [],
    renderCard = (it) => appCard(it),
    reorderEntry = (it) => it.id,
    onReorderLinks, onReorderGroups,
    isFiltering = false, canReorder = true, emptyNode = null,
  } = o;

  const entries = new Map();          // 卡片的 data-key -> 重排条目
  const buckets = new Map();
  items.forEach((it) => {
    const k = it.group_id ?? null;
    if (!buckets.has(k)) buckets.set(k, []);
    buckets.get(k).push(it);
  });

  const defs = groups.map((g) => ({ id: g.id, name: g.name }));
  defs.push({ id: null, name: '未分组' });

  if (!items.length && !groups.length && emptyNode) return emptyNode;

  const container = h('div', { class: 'spacesections' });
  let seq = 0;

  defs.forEach((def) => {
    const list = buckets.get(def.id) || [];
    if (isFiltering && !list.length) return;         // 筛选时不留空分组
    if (def.id === null && !list.length) return;     // 没东西就不用摆「未分组」

    const grid = h('div', {
      class: 'cardgrid',
      dataset: { gid: def.id === null ? '' : String(def.id) },
    });
    list.forEach((it) => {
      const key = `k${seq++}`;
      entries.set(key, reorderEntry(it));
      const card = renderCard(it);
      card.dataset.key = key;
      card.draggable = canReorder;
      grid.appendChild(card);
    });
    if (!list.length) {
      grid.appendChild(h('div', { class: 'groupempty', text: '这个分组还没有链接' }));
    }

    // 「未分组」不是真的分组（数据库里没有这个实体），它永远排最后，
    // 所以不给拖拽把手，也不让它被拖动——免得拖完刷新又跳回去。
    const movable = canReorder && def.id !== null;
    // draggable 必须用 DOM 属性设，不能走 setAttribute：
    // 它是枚举属性，setAttribute('draggable','') 的值非法，会退化成 auto（= 不可拖）。
    const head = h('div', { class: 'grouphead' },
      movable ? h('span', { class: 'grip', title: '拖动调整分组顺序' },
        icon('grip', 14)) : null,
      icon('folder', 13),
      h('span', { class: 'gname', text: def.name }),
      h('span', { class: 'gcount', text: list.length }));
    head.draggable = movable;

    container.appendChild(h('section', {
      class: 'groupsec',
      dataset: { gid: def.id === null ? '' : String(def.id) },
    }, head, grid));
  });

  // ── 拖拽 ──
  container.addEventListener('dragstart', (e) => {
    if (_pressOnWidget) { e.preventDefault(); return; }

    const sec = e.target.closest('.groupsec');
    const card = e.target.closest('.appcard');
    if (card && card.parentElement && card.parentElement.classList.contains('cardgrid')) {
      _dragCard = card;
      _dragGrid = card.parentElement;
      _origOrder = [..._dragGrid.children].map((el) => ({ parent: _dragGrid, el }));
    } else if (sec && sec.dataset.gid !== '' && e.target.closest('.grouphead') &&
               canReorder) {
      // 「未分组」不给拖（它永远排最后）
      _dragSection = sec;
      _origOrder = [...container.children].map((el) => ({ parent: container, el }));
    } else {
      return;
    }
    (card || sec).classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', 'ml');   // Firefox 需要 setData 才会真的开始拖
  });

  container.addEventListener('dragover', (e) => {
    if (_dragCard) {
      const grid = e.target.closest('.cardgrid');
      if (!grid || grid !== _dragGrid) return;    // 跨分组不放行
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      grid.insertBefore(_dragCard, cardRef(grid, e.clientX, e.clientY, _dragCard));
      _dropped = true;
      return;
    }
    if (_dragSection) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      container.insertBefore(_dragSection,
                             sectionRef(container, e.clientY, _dragSection));
      _dropped = true;
    }
  });

  // 提交：把界面上的新顺序整份发给后端。
  // drop 和 dragend 都会调（真的浏览器里 drop 先到，headless / 特殊情况可能只有其一），
  // 用 _committed 保证只提交一次。
  function commitDrop() {
    if (_committed || !_dropped) return;
    _committed = true;

    if (_dragCard && _dragGrid) {
      const gid = _dragGrid.dataset.gid === '' ? null : Number(_dragGrid.dataset.gid);
      const list = [..._dragGrid.children]
        .filter((el) => el.classList.contains('appcard'))
        .map((el) => entries.get(el.dataset.key))
        .filter((x) => x !== undefined);
      if (list.length) onReorderLinks?.(gid, list);
    } else if (_dragSection) {
      const gids = [...container.children]
        .map((el) => el.dataset.gid)
        .filter((v) => v !== '' && v !== undefined)
        .map(Number);
      if (gids.length) onReorderGroups?.(gids);
    }
  }

  container.addEventListener('drop', (e) => { e.preventDefault(); commitDrop(); });

  container.addEventListener('dragend', () => commitDrop());

  return container;
}
