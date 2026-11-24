# 检查：Enter 按钮只有 ↵，没有字（1.8.46）

现象（2026-11-24，公司电脑，1.8.44、1.8.45、1.8.46 都有）：第一次打开看板，Enter 按钮只有 ↵ 键，没有字；刷新浏览器就好了。

猜了两次都没修好，这次先拿数据：页面认为字在哪、是什么颜色、有没有动画还没停、强制重画以后字出不出来。

**关键：出现问题的时候不要刷新**，先做下面几步。

## 1. 打开 Console

在出问题的看板页面按 F12，点 **Console**。要是 Console 提示不让粘贴，先输入 `allow pasting` 回车。

## 2. 粘贴并运行

整段粘贴，回车：

```js
(() => {
  const l = document.querySelector(".en-lab"), go = document.querySelector(".en-go"), k = go && go.querySelector("kbd");
  if (!l) return console.log("NO .en-lab: the Enter screen is gone");
  const cs = (e) => getComputedStyle(e), r = (e) => { const b = e.getBoundingClientRect(); return [b.x, b.y, b.width, b.height].map(Math.round).join(","); };
  const anim = (e) => e.getAnimations().map((a) => a.playState + "@" + Math.round(a.currentTime || 0) + ":" + Object.keys(a.effect.getKeyframes()[0] || {}).filter((x) => !["offset", "easing", "composite", "computedOffset"].includes(x)).join("+")).join(" ") || "none";
  const out = [];
  out.push("A " + (document.querySelector(".en-legal") || {}).textContent + " | vis " + document.visibilityState + " focus " + document.hasFocus() + " dpr " + devicePixelRatio + " still " + (typeof MOTION !== "undefined" && MOTION.still()));
  out.push("B text [" + l.textContent + "] len " + l.textContent.length + " | go " + go.className);
  const s = cs(l);
  out.push("C lab op " + s.opacity + " color " + s.color + " fill " + s.webkitTextFillColor + " vis " + s.visibility + " | font " + s.fontWeight + " " + s.fontSize + " " + s.fontFamily.slice(0, 30));
  out.push("D lab rect " + r(l) + " | kbd rect " + (k ? r(k) : "-") + " kbd color " + (k ? cs(k).color : "-") + " | go rect " + r(go) + " go color " + cs(go).color + " bg " + cs(go).backgroundColor);
  out.push("E lab anims " + anim(l) + " | go anims " + anim(go));
  let up = [], e = l.parentElement;
  while (e && e !== document.body) { const c = cs(e); if (c.opacity !== "1" || c.filter !== "none" || c.visibility !== "visible" || e.getAnimations().length) up.push((e.id || e.className || e.tagName).toString().slice(0, 18) + " op" + c.opacity + " f:" + c.filter + " v:" + c.visibility + " a:" + e.getAnimations().length); e = e.parentElement; }
  out.push("F up " + (up.join(" / ") || "all plain"));
  const b = l.getBoundingClientRect(), hit = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
  out.push("G hit " + (hit ? (hit.className || hit.tagName).toString().slice(0, 30) : "-") + " | all anims on page " + document.getAnimations().length + " running " + document.getAnimations().filter((a) => a.playState === "running").length);
  out.push("H fonts " + document.fonts.status + " | html " + document.documentElement.className.slice(0, 60));
  console.log(out.join("\n"));
})();
```

拍照：整段输出（A 到 H 八行）。

## 3. 强制重画一次

再粘贴这一行，回车：

```js
(() => { const l = document.querySelector(".en-lab"); l.style.display = "none"; void l.offsetWidth; l.style.display = ""; return "redrawn"; })()
```

看按钮：**字出来了没有？**拍一张按钮的照片。

## 4. 字还没出来，再试一次

```js
(() => { const l = document.querySelector(".en-lab"); l.style.color = "red"; l.style.opacity = "1"; l.textContent = l.textContent + " "; return "red"; })()
```

看按钮：**有没有红字？**拍照。

## 5. 刷新以后对比

现在刷新浏览器。字出来以后，再跑一次第 2 步的整段，拍照。

## 6. 发回

四到五张照片：第 2 步、第 3 步按钮、（第 4 步按钮）、第 5 步。

## 怎么读（给 Claude）

- **B**：`text` 是空的 → 字根本没写进去（逻辑问题，看 `go` 的 class 是不是 `k-enter`）。
- **C**：`op` 小于 1，或 `color`/`fill` 是透明 → 页面自己把字藏了；**E** 看是哪个动画还挂着。
- **C** 正常、**E** 是 none，但看不见 → 画面没更新（显卡、远程桌面）；第 3 步能不能让字出来是关键。
- **D**：`lab rect` 宽度是 0 → 字被挤没了；不是 0 → 字占着位置。
- **F**：上面哪一层不透明度不是 1、有滤镜或还有动画。
- **G**：`hit` 不是 `en-lab` → 有别的东西盖在字上面。
- 第 5 步和第 2 步逐行比，不一样的那一行就是线索。
