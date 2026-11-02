# -*- coding: utf-8 -*-
"""把动态 SVG 渲染成 GIF 动图（微信公众号支持 GIF 动图）。

方案：用 SVG 内联脚本调用 setCurrentTime(t) 精确定位动画时间，
      每帧截图后合成 GIF。

为什么不用 --virtual-time-budget：
  它对 SMIL animateMotion 无效 —— 实测 18 帧像素哈希完全相同，
  即所有帧都是 t=0 的静止画面。

用法：python svg_to_gif.py <svg> <输出.gif> [帧数] [每帧毫秒] [周期ms]
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from PIL import Image

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def viewbox_size(svg_path):
    s = open(svg_path, encoding="utf-8").read()
    m = re.search(r'viewBox="([\d.\- ]+)"', s)
    vb = [float(x) for x in m.group(1).split()]
    return int(vb[2]), int(vb[3])


def make_paged_svg(svg_path, out_svg, t_value):
    """生成一个带 setCurrentTime 的临时 SVG，把动画钉在 t_value 时刻。"""
    s = open(svg_path, encoding="utf-8").read()
    # 用脚本在加载时把 SVG 时间轴设到指定值
    inject = (
        '<script type="text/javascript">'
        '<![CDATA['
        '(function(){'
        '  var s=document.documentElement;'
        '  function set(){ try{ s.setCurrentTime(' + f"{t_value:.4f}" + '); }catch(e){} }'
        '  if(s.pauseAnimations) s.pauseAnimations();'
        '  set();'
        '  window.addEventListener("load", function(){ set(); setTimeout(set,50); setTimeout(set,200); });'
        '  document.addEventListener("DOMContentLoaded", function(){ setTimeout(set,30); });'
        '})();'
        ']]>'
        '</script>'
    )
    # 插到 </svg> 前
    s2 = s.replace("</svg>", inject + "\n</svg>")
    with open(out_svg, "w", encoding="utf-8") as f:
        f.write(s2)
    return out_svg


def shoot(svg_path, out_png, w, h, profile_dir):
    """截一帧。

    两个必须注意的点：
    1. --user-data-dir 指向的目录必须**已存在**，否则 Chrome 静默失败
    2. 每次用独立目录，否则会撞 Chrome 单实例锁
    """
    os.makedirs(profile_dir, exist_ok=True)
    args = [
        CHROME, "--headless", "--disable-gpu", "--no-sandbox",
        "--hide-scrollbars", "--force-device-scale-factor=1",
        "--allow-file-access-from-files",
        f"--user-data-dir={profile_dir}",
        f"--screenshot={out_png}",
        f"--window-size={w},{h}",
        "--virtual-time-budget=1500",
        "--default-background-color=0B1220",
        f"file://{svg_path}",
    ]
    for attempt in range(3):
        try:
            subprocess.run(args, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=90)
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.4)
        if os.path.exists(out_png) and os.path.getsize(out_png) > 1000:
            return True
    return False


def build_gif(svg_path, out_gif, n_frames=20, frame_ms=90, period_ms=1400):
    # 必须是绝对路径：file:// + 相对路径 拼出来是无效 URL
    svg_path = os.path.abspath(svg_path)
    w, h = viewbox_size(svg_path)

    tmp = tempfile.mkdtemp(prefix="svg2gif_")
    frames = []
    try:
        for i in range(n_frames):
            t = period_ms * i / n_frames / 1000.0
            page = os.path.join(tmp, f"p{i:03d}.svg")
            make_paged_svg(svg_path, page, t)
            png = os.path.join(tmp, f"f{i:03d}.png")
            prof = os.path.join(tmp, f"prof{i:03d}")
            if not shoot(page, png, w, h, prof):
                print(f"  ❌ 第 {i} 帧截图失败")
                continue
            shutil.rmtree(prof, ignore_errors=True)
            frames.append(Image.open(png).convert("RGB"))
            print(f"  帧 {i+1}/{n_frames}  t={t:.3f}s", end="\r")

        if not frames:
            print("❌ 未捕获到任何帧")
            return None

        frames[0].save(
            out_gif, save_all=True, append_images=frames[1:],
            duration=frame_ms, loop=0, optimize=True, disposal=2,
        )

        # 校验帧是否真的有差异
        import hashlib
        sigs = {hashlib.md5(f.tobytes()).hexdigest() for f in frames}
        print(f"\n✅ 已生成 {out_gif}")
        print(f"   {len(frames)} 帧 / {w}x{h} / "
              f"{os.path.getsize(out_gif)//1024} KB")
        print(f"   唯一帧数 {len(sigs)}/{len(frames)}"
              f"{'  ✅ 动画有效' if len(sigs) > 1 else '  ⚠️ 所有帧相同，动画未生效'}")
        return out_gif
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    svg = sys.argv[1]
    out = sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    ms = int(sys.argv[4]) if len(sys.argv) > 4 else 90
    period = int(sys.argv[5]) if len(sys.argv) > 5 else 1400
    build_gif(svg, out, n, ms, period)
