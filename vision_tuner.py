"""
vision_tuner.py —— 調每個顏色的 HSV, 存進 vision_profiles.json (放置板與隨機板的顏色都存這一個檔)

操作:
  1. 把物件放到鏡頭下, 拖三條滑桿的把手, 直到右邊 mask 只剩物件是白的、背景全黑
  2. 按 s → 在終端輸入顏色名 (小寫, 例 red) → 存檔 (同名會覆蓋)
  3. 換下一個物件, 重複 1~2
  4. 按 q 離開

鍵位: s = 存檔   n = 載入下一個已存的顏色來修改   q = 離開
"""
import os
import cv2
import numpy as np

import camera_config as cam
from color_detect import DetectConfig, detect_objects, load_profiles, save_profiles

PROFILES_FILE = "vision_profiles.json"
WIN = "tuner"

# ---------- 版面尺寸 (畫布座標, 單位: 像素) ----------
PANEL_W, PANEL_H = 640, 360         # 相機畫面與 mask 各縮成這個大小並排 (1280x720 的一半)
CANVAS_W = PANEL_W * 2              # 畫布總寬 = 兩個面板
SLIDER_TOP = PANEL_H + 24           # 第一條滑桿的中心 y
SLIDER_GAP = 46                     # 滑桿之間的距離
SLIDER_X0, SLIDER_X1 = 150, CANVAS_W - 40   # 滑桿軌道左右端 x
TRACK_H = 14                        # 軌道高度
HANDLE_R = 10                       # 把手半徑
CANVAS_H = SLIDER_TOP + SLIDER_GAP * 3 + 30 # 畫布總高 (三條滑桿 + 一行狀態文字)

# ---------- 顏色 (BGR) ----------
BG = (32, 32, 32)                   # 畫布底色 (深灰)
TEXT = (235, 235, 235)              # 文字 (淺色, 和底色對比清楚)
HANDLE_FILL, HANDLE_EDGE = (250, 250, 250), (0, 0, 0)
TRACK_OFF, TRACK_ON = (70, 70, 70), (235, 235, 235)   # 軌道: 沒選到 = 深灰, 選到 = 白

# 三條滑桿: (顯示名, cfg 的 min 欄位, cfg 的 max 欄位, 最大值)
SLIDERS = [
    ("H", "h_min", "h_max", 179),
    ("S", "s_min", "s_max", 255),
    ("V", "v_min", "v_max", 255),
]


# ---------- 座標 ↔ 數值 ----------
def val_to_x(v, maxv):
    """滑桿數值 → 畫布 x。"""
    return int(round(SLIDER_X0 + (SLIDER_X1 - SLIDER_X0) * v / maxv))


def x_to_val(x, maxv):
    """畫布 x → 滑桿數值 (夾在 0..maxv)。"""
    v = (x - SLIDER_X0) * maxv / (SLIDER_X1 - SLIDER_X0)
    return int(round(min(max(v, 0), maxv)))


def slider_cy(i):
    """第 i 條滑桿的中心 y。"""
    return SLIDER_TOP + SLIDER_GAP * i


# ---------- 滑鼠 ----------
class Mouse:
    """記住目前拖的是哪條滑桿的哪個把手; 拖曳時直接改 cfg。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.drag = None            # None 或 (滑桿編號, "min"/"max")

    def callback(self, event, x, y, flags, _param):
        # 注意: OpenCV 傳進來的 x, y 是「畫布上的像素座標」, 視窗被拉大縮小時它會自己換算回來
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drag = self._hit(x, y)
            if self.drag:
                self._apply(x)
        elif event == cv2.EVENT_MOUSEMOVE and self.drag and (flags & cv2.EVENT_FLAG_LBUTTON):
            self._apply(x)
        elif event == cv2.EVENT_LBUTTONUP:
            self.drag = None

    def _hit(self, x, y):
        """點在哪條滑桿上? 回傳離點擊處最近的那個把手。"""
        for i, (_n, fmin, fmax, maxv) in enumerate(SLIDERS):
            if abs(y - slider_cy(i)) <= HANDLE_R + 6:
                dmin = abs(x - val_to_x(getattr(self.cfg, fmin), maxv))
                dmax = abs(x - val_to_x(getattr(self.cfg, fmax), maxv))
                return (i, "min" if dmin <= dmax else "max")
        return None

    def _apply(self, x):
        """把正在拖的把手移到 x 對應的數值。"""
        i, which = self.drag
        _n, fmin, fmax, maxv = SLIDERS[i]
        v = x_to_val(x, maxv)
        if i == 0:                                   # H: 允許 min 越過 max → 兩段模式
            setattr(self.cfg, fmin if which == "min" else fmax, v)
        elif which == "min":                         # S/V: min 不能超過 max
            setattr(self.cfg, fmin, min(v, getattr(self.cfg, fmax)))
        else:
            setattr(self.cfg, fmax, max(v, getattr(self.cfg, fmin)))


# ---------- 畫 ----------
def draw_slider(canvas, i, cfg):
    """畫第 i 條滑桿: 名字 + 目前範圍 + 軌道 (選到的區段亮、其他暗) + 兩個把手。"""
    name, fmin, fmax, maxv = SLIDERS[i]
    lo, hi = getattr(cfg, fmin), getattr(cfg, fmax)
    cy = slider_cy(i)
    y0 = cy - TRACK_H // 2

    # 整條軌道先塗深灰, 再把選到的區段塗白。H 若 lo > hi 代表兩段 (0..hi 和 lo..179)
    y1 = y0 + TRACK_H
    xl, xh = val_to_x(lo, maxv), val_to_x(hi, maxv)
    canvas[y0:y1, SLIDER_X0:SLIDER_X1] = TRACK_OFF
    if lo <= hi:
        canvas[y0:y1, xl:xh + 1] = TRACK_ON
    else:
        canvas[y0:y1, SLIDER_X0:xh + 1] = TRACK_ON
        canvas[y0:y1, xl:SLIDER_X1] = TRACK_ON

    # 左邊文字: 名字與數值
    cv2.putText(canvas, f"{name} {lo:3d} ~ {hi:3d}", (14, cy + 7),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, TEXT, 1, cv2.LINE_AA)

    # 兩個把手
    for v in (lo, hi):
        x = val_to_x(v, maxv)
        cv2.circle(canvas, (x, cy), HANDLE_R, HANDLE_FILL, -1, cv2.LINE_AA)
        cv2.circle(canvas, (x, cy), HANDLE_R, HANDLE_EDGE, 2, cv2.LINE_AA)


def draw_canvas(frame, mask, objs, cfg):
    """組出整張畫布: 上面兩個面板, 下面三條滑桿和狀態列。"""
    canvas = np.full((CANVAS_H, CANVAS_W, 3), BG, np.uint8)

    # 左面板: 相機畫面縮小 + 偵測到的物件輪廓 / 中心 / 像素座標 (座標仍是原圖 1280x720 的)
    sx, sy = PANEL_W / frame.shape[1], PANEL_H / frame.shape[0]
    view = cv2.resize(frame, (PANEL_W, PANEL_H))
    for i, o in enumerate(objs):
        c = (0, 255, 0) if i == 0 else (0, 220, 220)     # 面積最大的用綠色
        cnt = (o["contour"].astype(np.float32) * (sx, sy)).astype(np.int32)
        cv2.drawContours(view, [cnt], -1, c, 2)
        px, py = int(o["cx"]), int(o["cy"])
        vx, vy = int(px * sx), int(py * sy)
        cv2.drawMarker(view, (vx, vy), c, cv2.MARKER_CROSS, 14, 2)
        cv2.putText(view, f"#{i} ({px},{py})", (vx + 6, vy - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1, cv2.LINE_AA)
    canvas[0:PANEL_H, 0:PANEL_W] = view

    # 右面板: mask (單通道 → 三通道才能貼進彩色畫布)
    mask_bgr = cv2.cvtColor(cv2.resize(mask, (PANEL_W, PANEL_H)), cv2.COLOR_GRAY2BGR)
    canvas[0:PANEL_H, PANEL_W:CANVAS_W] = mask_bgr

    # 面板標題
    cv2.putText(canvas, "camera", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(canvas, "mask", (PANEL_W + 8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)

    # 三條滑桿
    for i in range(len(SLIDERS)):
        draw_slider(canvas, i, cfg)

    # 狀態列
    cv2.putText(canvas, f"editing: {cfg.name or '(new)'}   objs={len(objs)}    s=save  n=next  q=quit",
                (14, CANVAS_H - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, TEXT, 1, cv2.LINE_AA)
    return canvas


# ---------- 存檔 ----------
def save(cfg, profiles):
    """按 s: 問顏色名, 同名覆蓋, 存檔。"""
    name = input("  顏色名 (小寫, 例 red; 直接 Enter 取消): ").strip().lower()
    if not name:
        return
    cfg = DetectConfig(**vars(cfg))     # 複製一份再存, 免得之後拉滑桿改到存進去的那份
    cfg.name = name
    profiles[:] = [p for p in profiles if p.name != name] + [cfg]
    save_profiles(profiles, PROFILES_FILE)
    print(f"  已存 '{name}' → {PROFILES_FILE}  (目前有: {', '.join(p.name for p in profiles)})")


# ---------- 主程式 ----------
def main():
    profiles = load_profiles(PROFILES_FILE) if os.path.exists(PROFILES_FILE) else []
    cfg = DetectConfig(**vars(profiles[0])) if profiles else DetectConfig()
    idx = 0

    cap = cam.open_camera()
    if cap is None:
        print("[tuner] 開不了相機")
        return

    # WINDOW_NORMAL = 使用者可以拖邊框改視窗大小 (預設的 AUTOSIZE 不行)
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, CANVAS_W, CANVAS_H)
    mouse = Mouse(cfg)
    cv2.setMouseCallback(WIN, mouse.callback)
    print(__doc__)

    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        objs, mask = detect_objects(frame, cfg)     # cfg 會被滑鼠 callback 即時改掉
        cv2.imshow(WIN, draw_canvas(frame, mask, objs, cfg))

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break
        elif key == ord('s'):
            save(cfg, profiles)
        elif key == ord('n') and profiles:          # 切到下一個已存的顏色
            idx = (idx + 1) % len(profiles)
            cfg = DetectConfig(**vars(profiles[idx]))
            mouse.cfg = cfg                         # 滑鼠要改的也換成新的 cfg
            print(f"  載入 '{cfg.name}'")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
