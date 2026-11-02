# -*- coding: utf-8 -*-
"""电商架构双向动态流程图 —— SVG 生成器（含几何自检）。

按 dynamic-two-way-flowchart 技能规范实现：
  - 三阶段配色（认证/发现/调用）
  - 去程实线 + 粒子，返回虚线 + 暗灰粒子
  - 核心枢纽脉动、状态灯呼吸
  - 生成后逐条自检：标签 vs 节点、标签 vs 标签、连线 vs 节点、往返不同 y

节点/连线全部用绝对坐标描述，便于程序化校验。
"""
import sys

# ---------------------------------------------------------------- 样式常量
BG = "#0B1220"
GRID = "rgba(96,165,250,0.12)"
NODE_FILL = "#101A2E"
NODE_EDGE = "#3A4A63"
CORE_FILL = "#0E2B1F"
CORE_EDGE = "#3EF08C"
TXT = "#E8EEF7"
SUB = "#8FA3BF"
ACCENT = "#5FE3D2"
LBL_MUTED = "#7A8CA8"
HUD = "#2C3E58"

PHASE = {
    "auth":   {"stroke": "#4F8EF7", "label": "#7FB0FF", "marker": "arrBlue"},
    "disc":   {"stroke": "#2DD4BF", "label": "#5FE3D2", "marker": "arrTeal"},
    "invoke": {"stroke": "#3EF08C", "label": "#3EF08C", "marker": "arrGreen"},
}
RET = {"stroke": "#5A6B88", "marker": "arrRet"}
# 返回粒子/标签在深色底上需可见 —— 用亮一档的灰蓝
RET_PARTICLE = "#B0C0D8"
RET_HALO = "#5A6B88"
RET_LABEL = "#A3B4CC"

# ---------------------------------------------------------------- 节点
# id: (标签, 副标, x, y, w, h, is_core)
NODES = {
    "client":  ("客户端",   "App / Web",      25,  255, 110, 70,  False),
    "gateway": ("API 网关", "鉴权·限流·路由", 185, 220, 145, 140, True),
    "auth":    ("认证服务", "SSO / Token",    195,  65, 140, 70,  False),
    "goods":   ("商品服务", "商品·库存",      470,  95, 140, 80,  False),
    "order":   ("订单服务", "订单创建",       470, 255, 140, 95,  False),
    "pay":     ("支付服务", "支付回调",       470, 430, 140, 80,  False),
    "mq":      ("消息队列", "MQ 异步",        190, 430, 160, 75,  False),
    "db":      ("数据库",   "MySQL / Redis",  25,  430, 125, 75,  False),
}

# ---------------------------------------------------------------- 连线
# (from, to, phase, 折线点列表, 标签, 标签锚点[x,y], 标签对齐)
# phase=None 表示返回（虚线）
EDGES = [
    # 客户端 → 网关（去程/回程共用左边，分不同 y；标签缩短以避开节点）
    ("client", "gateway", "invoke", [(135, 285), (185, 285)], "下单", (160, 303), "middle"),
    ("client", "gateway", None,     [(185, 320), (135, 320)], "响应", (160, 338), "middle"),

    # 网关 → 认证服务（向上闭环，往返错开 x）
    ("gateway", "auth", "auth", [(250, 220), (250, 135)], "Token 校验", (240, 182), "end"),
    ("auth", "gateway", None,    [(300, 135), (300, 220)], "鉴权结果",   (310, 182), "start"),

    # 网关 → 商品服务
    ("gateway", "goods", "disc", [(330, 240), (400, 240), (400, 125), (470, 125)], "商品查询", (435, 113), "middle"),
    ("goods", "gateway", None,   [(470, 155), (440, 155), (440, 280), (330, 280)], "商品信息", (378, 268), "middle"),

    # 网关 → 订单服务
    ("gateway", "order", "invoke", [(330, 315), (470, 315)], "创建订单", (400, 303), "middle"),
    ("order", "gateway", None,     [(470, 340), (330, 340)], "订单号",     (400, 356), "middle"),

    # 订单服务 → 支付服务（往返错开 x）
    ("order", "pay", "invoke", [(535, 350), (535, 430)], "发起支付", (548, 380), "start"),
    ("pay", "order", None,     [(575, 430), (575, 350)], "支付结果", (563, 410), "end"),

    # 订单服务 → 消息队列
    ("order", "mq", "invoke", [(500, 350), (500, 395), (270, 395), (270, 430)], "发货事件", (385, 386), "middle"),

    # 消息队列 → 数据库
    ("mq", "db", "disc", [(190, 467), (150, 467)], "落库", (170, 456), "middle"),
]

# 主链按真实依赖排序；异步分支在支付成功后独立执行，不等待客户端响应。
EDGES = [EDGES[i] for i in (0, 2, 3, 4, 5, 6, 8, 9, 7, 1, 10, 11)]
STEPS = [str(i) for i in range(1, 11)] + ["9a", "9b"]
STARTS = [i * 1.3 for i in range(10)] + [10.4, 11.7]
EDGES = [(*edge[:4], f"{step} {edge[4]}", *edge[5:])
         for step, edge in zip(STEPS, EDGES)]
# 最后两条异步连线的编号标签移到宽敞位置。
EDGES[-2] = (*EDGES[-2][:4], "9a 异步发货", (385, 386), "middle")
EDGES[-1] = (*EDGES[-1][:4], "9b 异步落库", (170, 525), "middle")

# ---------------------------------------------------------------- 几何工具
def rects_overlap(a, b, pad=0):
    """两个矩形是否相交（pad 为额外间距）。"""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw + pad <= bx or bx + bw + pad <= ax
                or ay + ah + pad <= by or by + bh + pad <= ay)


def seg_rect_cross(p, q, r, pad=0):
    """线段 p-q 是否与矩形 r 相交（端点落在矩形内视为相交）。"""
    px, py = p
    qx, qy = q
    rx, ry, rw, rh = r
    x0, y0 = rx - pad, ry - pad
    x1, y1 = rx + rw + pad, ry + rh + pad
    # 端点在矩形内
    for (x, y) in (p, q):
        if x0 <= x <= x1 and y0 <= y <= y1:
            return True
    # 线段与四条边相交
    edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
             ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
    for (a, b) in edges:
        if seg_seg_cross(p, q, a, b):
            return True
    return False


def seg_seg_cross(p1, p2, p3, p4):
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])
    return (ccw(p1, p3, p4) != ccw(p2, p3, p4)
            and ccw(p1, p2, p3) != ccw(p1, p2, p4))


def text_bbox(cx, cy, text, size=12, anchor="middle"):
    """估算文本包围盒（中文按 size 宽，ASCII 按 0.55*size）。"""
    w = 0
    for ch in text:
        w += size if ord(ch) > 0x2E80 else size * 0.55
    if anchor == "middle":
        x0 = cx - w / 2
    elif anchor == "end":
        x0 = cx - w
    else:
        x0 = cx
    return (x0, cy - size * 0.8, w, size)


# ---------------------------------------------------------------- 自检
def verify(verbose=True):
    problems = []

    # 1) 连线不穿过任何节点矩形
    for (f, t, phase, pts, label, lp, anchor) in EDGES:
        for i in range(len(pts) - 1):
            p, q = pts[i], pts[i + 1]
            for nid, (nl, ns, x, y, w, h, core) in NODES.items():
                if nid in (f, t):
                    # 端点所属节点：只检查起点/终点那一段
                    if i == 0 and nid == f:
                        continue
                    if i == len(pts) - 2 and nid == t:
                        continue
                if seg_rect_cross(p, q, (x, y, w, h), pad=2):
                    problems.append(f"连线 {f}→{t} 段{i} 穿过节点 {nl}({nid})")

    # 2) 标签不与节点相交
    for (f, t, phase, pts, label, lp, anchor) in EDGES:
        bb = text_bbox(lp[0], lp[1], label, 10, anchor)
        for nid, (nl, ns, x, y, w, h, core) in NODES.items():
            if rects_overlap(bb, (x, y, w, h), pad=3):
                problems.append(f"标签「{label}」与节点 {nl}({nid}) 相交")

    # 3) 相邻标签互不相交
    labels = [(text_bbox(lp[0], lp[1], lb, 10, an), lb)
              for (f, t, ph, pts, lb, lp, an) in EDGES]
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            if rects_overlap(labels[i][0], labels[j][0], pad=4):
                problems.append(f"标签「{labels[i][1]}」与「{labels[j][1]}」重叠")

    # 4) 同一对节点的往返线不在同一高度（仅对水平段有意义；竖直平行段按 x 区分）
    for i in range(len(EDGES)):
        for j in range(i + 1, len(EDGES)):
            a, b = EDGES[i], EDGES[j]
            if {a[0], a[1]} == {b[0], b[1]} and (a[2] is None) != (b[2] is None):
                # 水平段：y 必须不同
                ha = {p[1] for p in a[3] if p[0] == a[3][0][0]}   # 水平段的 y
                hb = {p[1] for p in b[3] if p[0] == b[3][0][0]}
                # 竖直段：x 必须不同
                va = {p[0] for p in a[3] if p[1] == a[3][0][1]}
                vb = {p[0] for p in b[3] if p[1] == b[3][0][1]}
                if (ha & hb) and (va & vb):
                    problems.append(f"{a[0]}↔{a[1]} 往返线重合 "
                                    f"y={ha & hb} x={va & vb}")

    if verbose:
        if problems:
            print("❌ 几何自检未通过：")
            for p in problems:
                print("   -", p)
        else:
            print("✅ 几何自检全部通过")
    return problems


# ---------------------------------------------------------------- 生成 SVG
def build_svg():
    # 内容包围盒
    xs, ys = [], []
    for nl, ns, x, y, w, h, core in NODES.values():
        xs += [x, x + w]
        ys += [y, y + h]
    for (f, t, ph, pts, lb, lp, an) in EDGES:
        for (px, py) in pts:
            xs.append(px); ys.append(py)
        for (px, py) in [(lp[0], lp[1])]:
            xs.append(px); ys.append(py)
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    M = 40
    vx, vy = 0, 0
    vw, vh = maxx + M, maxy + M + 110

    L = []
    L.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="{vx} {vy} {vw:.0f} {vh:.0f}" role="img" aria-label="电商架构双向动态流程图">')
    L.append('''  <style>
    text { font-family: "PingFang SC", "SF Pro Text", system-ui, sans-serif; }
    .nodeText { fill: #E8EEF7; font-size: 14px; font-weight: 500; }
    .nodeSub { fill: #8FA3BF; font-size: 11px; }
    .labBlue { fill: #7FB0FF; font-size: 12px; font-weight: 500; }
    .labTeal { fill: #5FE3D2; font-size: 12px; font-weight: 500; }
    .labGreen { fill: #3EF08C; font-size: 12px; font-weight: 500; }
    .labMuted { fill: #A3B4CC; font-size: 12px; font-weight: 500; }
    .labBlue, .labTeal, .labGreen, .labMuted { font-size: 10px; }
    .stepNumber { fill: #E8EEF7; font-size: 10px; font-weight: 700; text-anchor: middle; dominant-baseline: central; }
    @media (prefers-reduced-motion: no-preference) {
      .pulse { animation: pulse 1.8s ease-in-out infinite; }
      .blink { animation: blink 1.6s ease-in-out infinite; }
    }
    @keyframes dashFlow { to { stroke-dashoffset: -32; } }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity:  0.6; } }
    @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
    @media (prefers-reduced-motion: reduce) { .particles { opacity: 0; } }
  </style>''')
    L.append('''  <defs>
    <pattern id="grid" width="26" height="26" patternUnits="userSpaceOnUse">
      <circle cx="13" cy="13" r="1.0" fill="rgba(96,165,250,0.12)" />
    </pattern>''')
    for mid, col in (("arrBlue", "#4F8EF7"), ("arrTeal", "#2DD4BF"),
                     ("arrGreen", "#3EF08C"), ("arrRet", "#5A6B88")):
        L.append(f'''    <marker id="{mid}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto">
      <path d="M1 1 L7 4 L1 7 Z" fill="{col}" />
    </marker>''')
    L.append("  </defs>")
    L.append(f'  <rect x="{vx}" y="{vy}" width="{vw:.0f}" height="{vh:.0f}" fill="{BG}" />')
    L.append(f'  <rect x="{vx}" y="{vy}" width="{vw:.0f}" height="{vh:.0f}" fill="url(#grid)" />')

    # HUD 四角
    L.append(f'  <path d="M{vx+14} {vy+40} V{vy+14} H{vx+40}" fill="none" stroke="{HUD}" stroke-width="1.2" stroke-linecap="round" />')
    L.append(f'  <path d="M{vx+vw-40} {vy+40} V{vy+14} H{vx+vw-14}" fill="none" stroke="{HUD}" stroke-width="1.2" stroke-linecap="round" />')
    L.append(f'  <path d="M{vx+14} {vy+vh-40} V{vy+vh-14} H{vx+40}" fill="none" stroke="{HUD}" stroke-width="1.2" stroke-linecap="round" />')
    L.append(f'  <path d="M{vx+vw-40} {vy+vh-40} V{vy+vh-14} H{vx+vw-14}" fill="none" stroke="{HUD}" stroke-width="1.2" stroke-linecap="round" />')

    def path_of(pts):
        return "M" + " L".join(f"{x} {y}" for x, y in pts)

    # --- 连线层
    for (f, t, phase, pts, label, lp, an) in EDGES:
        d = path_of(pts)
        if phase is None:
            L.append(f'  <path d="{d}" fill="none" stroke="{RET["stroke"]}" stroke-width="1.0" '
                     f'stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="5 7" marker-end="url(#{RET["marker"]})" />')
        else:
            st = PHASE[phase]["stroke"]
            wd = "1.4" if phase == "invoke" else "1.2"
            cls = "class=\"flow\"" if phase != "invoke" else ""
            L.append(f'  <path {cls} d="{d}" fill="none" stroke="{st}" stroke-width="{wd}" '
                     f'stroke-linecap="round" stroke-linejoin="round" marker-end="url(#{PHASE[phase]["marker"]})" />')

    # --- 粒子层
    L.append('<g visibility="hidden"><animate id="flowCycle" attributeName="opacity" from="0" to="0" begin="0s" dur="15s" repeatCount="indefinite" /></g>')
    L.append('  <g class="particles">')
    for step, delay, (f, t, phase, pts, label, lp, an) in zip(STEPS, STARTS, EDGES):
        d = path_of(pts)
        c = PHASE[phase]["stroke"] if phase else RET_PARTICLE
        begin = f"{delay:.1f}s;flowCycle.repeatEvent+{delay:.1f}s"
        L.append(f'''    <g data-step="{step}" visibility="hidden">
      <set attributeName="visibility" to="visible" begin="{begin}" dur="1.2s" />
      <animateMotion dur="1.2s" begin="{begin}" path="{d}" />
      <circle r="14" fill="{c}" opacity="0.35" />
      <circle r="10" fill="{BG}" stroke="{c}" stroke-width="1.5" />
      <text class="stepNumber">{step}</text>
    </g>''')
    L.append("  </g>")

    # --- 节点层
    for nid, (nl, ns, x, y, w, h, core) in NODES.items():
        cls = ' class="pulse"' if core else ""
        fill = CORE_FILL if core else NODE_FILL
        stroke = CORE_EDGE if core else NODE_EDGE
        sw = "1.4" if core else "1.2"
        L.append(f'  <g{cls}>')
        L.append(f'    <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" />')
        L.append(f'    <circle class="blink" cx="{x+w-8}" cy="{y+11}" r="3" fill="#3EF08C" />')
        L.append(f'    <text class="nodeText" x="{x+w/2}" y="{y+26 if ns else y+38}" text-anchor="middle">{nl}</text>')
        if ns:
            L.append(f'    <text class="nodeSub" x="{x+w/2}" y="{y+44}" text-anchor="middle">{ns}</text>')
        L.append("  </g>")

    # --- 标签层
    for (f, t, phase, pts, label, lp, an) in EDGES:
        if phase is None:
            cls = "labMuted"
        else:
            cls = {"auth": "labBlue", "disc": "labTeal", "invoke": "labGreen"}[phase]
        L.append(f'  <text class="{cls}" x="{lp[0]}" y="{lp[1]}" text-anchor="{an}">{label}</text>')

    for offset, note in enumerate((
        "示例假定鉴权通过、支付成功；9a/9b 为支付成功后的异步分支，不阻塞响应。整轮 15s。",
        "编号不等于严格时序图：编号与动画表示逻辑调用顺序，",
        "不代表真实耗时、精确时间比例或完整的并发时序。",
    )):
        L.append(f'<text x="40" y="{maxy + 35 + offset * 20}" fill="{SUB}" font-size="10">{note}</text>')
    L.append("</svg>")
    return "\n".join(L)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "ecom.svg"
    probs = verify()
    if probs:
        sys.exit(1)
    svg = build_svg()
    with open(out, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"✅ 已生成 {out}（{len(svg)} 字符）")
