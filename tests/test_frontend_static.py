#!/usr/bin/env python3
"""前端静态检查——不需要起服务，直接读 web/ 下的源码。

存在的意义：有些坑在运行时才暴露，而且只在特定数据下才出现（比如某个空间
恰好没有标签）。这种「碰巧安全」的代码最难查，不如在源码层面直接钉死。

目前钉住的规则：

1. 不许出现原生 `replaceChildren`。它按 WebIDL 规则把参数转成节点或字符串，
   `null` 会变成一个内容为 "null" 的文本节点，页面上就凭空多出一个 null。
   统一用 ui.js 的 `setChildren(el, ...)`，它和 `h()` 一样跳过 null/undefined/false。
   （踩过两次：公开页没有标签时的筛选条、空间列表只有一页时的分页器。）

2. `h()` 的 `text` 属性只接受字符串。传数字没问题（会走 setAttribute/textContent
   自动转换），但传对象会渲染成 "[object Object]"，所以在源码里挡住明显的对象字面量。

3. 所有 `fetch(` 都要带 `credentials`，否则接口的会话 cookie 不会带上，
   表现为「刚登录完又是未登录」。

4. 业务代码里不许裸用 `navigator.clipboard`，一律走 ui.js 的 `copyText()`。
   剪贴板 API 只在**安全上下文**下存在（HTTPS 或 localhost/127.0.0.1）——
   内网常见的 `http://<内网IP>:3030`、`http://<内部域名>/` 都不算，
   那时 `navigator.clipboard` 是 undefined，直接调会抛 TypeError，
   表现成「凡是带复制的地方全都失灵」。`copyText()` 里带 execCommand 兜底。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

PASS = 0
FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}   {extra}")


def js_files():
    return sorted(WEB.rglob("*.js"))


def strip_comments(src: str) -> str:
    """去掉 // 行注释和 /* */ 块注释，免得规则被注释里的示例文本误伤。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    src = re.sub(r"(?m)\s//\s.*$", "", src)
    return src


def main():
    files = js_files()
    check("找得到前端文件", len(files) >= 6, f"只有 {len(files)} 个: {[f.name for f in files]}")

    sources = {f: strip_comments(f.read_text(encoding="utf-8")) for f in files}
    ui = sources.get(WEB / "js" / "ui.js", "")

    print()
    print("── 规则 1：别用原生 replaceChildren（null 会渲染成 \"null\"）──")
    check("ui.js 里有 setChildren 封装", "export function setChildren" in ui)
    offenders = []
    for f, src in sources.items():
        for i, line in enumerate(src.splitlines(), 1):
            if "replaceChildren" in line:
                offenders.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()[:70]}")
    check("业务代码里没有 replaceChildren", not offenders,
          "\n        ".join([""] + offenders))

    print()
    print("── 规则 2：h() 的 text 不要传对象字面量 ──")
    bad_text = []
    for f, src in sources.items():
        for m in re.finditer(r"text:\s*(\{[^}]*\})", src):
            line_no = src[:m.start()].count("\n") + 1
            bad_text.append(f"{f.relative_to(ROOT)}:{line_no}: text: {m.group(1)[:50]}")
    check("没有 text: {...} 这种写法", not bad_text, "\n        ".join([""] + bad_text))

    print()
    print("── 规则 3：fetch 必须带 credentials ──")
    no_cred = []
    for f, src in sources.items():
        for m in re.finditer(r"fetch\(", src):
            # 取这次 fetch 调用的前 400 字符，看有没有 credentials
            seg = src[m.start(): m.start() + 400]
            seg = seg[: seg.find(";") + 1 or 400]
            if "credentials" not in seg:
                line_no = src[:m.start()].count("\n") + 1
                no_cred.append(f"{f.relative_to(ROOT)}:{line_no}: {seg.splitlines()[0][:60]}")
    check("每个 fetch 都带 credentials", not no_cred, "\n        ".join([""] + no_cred))

    print()
    print("── 规则 4：剪贴板一律走 copyText（非安全上下文下 navigator.clipboard 不存在）──")
    check("ui.js 里有 copyText 封装", "export async function copyText" in ui)
    clip = []
    for f, src in sources.items():
        if f.name == "ui.js":
            continue          # 封装自己当然要用
        for i, line in enumerate(src.splitlines(), 1):
            if "navigator.clipboard" in line:
                clip.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()[:70]}")
    check("业务代码里没有裸用 navigator.clipboard", not clip,
          "\n        ".join([""] + clip))

    print()
    print("=" * 46)
    print(f"结果: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
