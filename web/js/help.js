// 使用指南页（/help）
//
// 干三件事：填顶栏、给左侧目录做滚动高亮、管右下角的返回顶部。
// 正文是 help.html 里的静态 HTML —— 指南这种东西脚本挂了也得能读，
// 所以这里一行正文都不渲染。同理，顶栏和按钮的初始态都是「不显示」，
// 脚本没跑起来时页面只是少了这两个部件，不会缺内容。
import { h, setChildren, brand, accountArea, currentUser } from './ui.js';

// ── 顶栏 ──
// 要探一次会话，才知道右上角该显示登录态还是「登录」。
const top = document.getElementById('helptop');
const user = await currentUser();
setChildren(top,
  h('div', { class: 'pubheadtop' },
    brand({ title: '返回链接广场' }), accountArea(user)));

// ── 左侧目录：滚动时高亮当前章节 ──
// 判定线放在视口上方 120px 处，取「已滚过这条线的最后一个章节」。
// 比 IntersectionObserver 简单，也不会在一屏里同时命中多个章节时来回抖。
const navLinks = [...document.querySelectorAll('.helpnav a')];
const sections = navLinks
  .map((a) => document.getElementById(a.getAttribute('href').slice(1)))
  .filter(Boolean);

function markCurrent() {
  if (!sections.length) return;
  const line = window.scrollY + 120;
  let cur = sections[0];
  for (const s of sections) {
    if (s.getBoundingClientRect().top + window.scrollY <= line) cur = s;
  }
  // 已经到底时，最后一章可能永远越不过判定线（页面不够长），直接点亮它
  if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 2) {
    cur = sections[sections.length - 1];
  }
  for (const a of navLinks) {
    a.classList.toggle('on', a.getAttribute('href') === `#${cur.id}`);
  }
}

// ── 返回顶部 ──
const toTop = document.getElementById('totop');

function markToTop() {
  toTop.classList.toggle('on', window.scrollY > 400);
}

toTop.addEventListener('click', () => {
  const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  window.scrollTo({ top: 0, behavior: smooth ? 'smooth' : 'auto' });
  // 按钮马上要隐身了，焦点别留在它身上（键盘用户会 Tab 到一个看不见的东西）
  toTop.blur();
});

// scroll 事件很密，直接在里面算布局会掉帧 —— 用 rAF 节流，一帧最多算一次
let queued = false;
function onScroll() {
  if (queued) return;
  queued = true;
  requestAnimationFrame(() => { queued = false; markCurrent(); markToTop(); });
}
window.addEventListener('scroll', onScroll, { passive: true });
window.addEventListener('resize', onScroll, { passive: true });
markCurrent();
markToTop();
