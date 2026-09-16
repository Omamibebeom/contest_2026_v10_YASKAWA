"""
affine_sample_tool.py —— 像素↔手臂 取樣工具 (賽前跑; 不存檔, 點位印在終端)

兩段式取樣 (避免手臂進場被誤偵測):
  1) 放好基準物件 → 畫面顯示 (cx,cy) → 按 SPACE 鎖定 (偵測凍結)
  2) 手臂 Jog 到同一點 → 按 c 輸入手臂教導器顯示的 X,Y → 完成一點並自動解鎖

鍵位: SPACE=鎖定  x=解鎖  c=輸入手臂座標  u=刪上一點
      p=印出 PIXELS/ARMS 清單  q/ESC=離開(自動印一次)

取樣建議: 鋪滿隨機位置放置板 (四角＋中間), 至少 3 點、不可排成一直線。
點位抄進 affine_transform.py 後, 用 python3 affine_transform.py 驗算。
基準物件: 任一件 b 物件都可以 (畫面上面積最大的那件會被鎖定)。
"""
import cv2

import camera_config as cam
from color_detect import load_profiles, detect_with_profiles

PROFILES_FILE = "vision_profiles.json"  # vision_tuner.py 按 s 存的各色 HSV


def _ask_arm_xy():
    """終端輸入手臂 X,Y (格式 'X,Y' 或 'X Y'); 空白取消。"""
    s = input("  輸入手臂座標 X,Y (例 712.3,55.8 ; Enter 取消): ").strip()
    if not s:
        return None
    try:
        x, y = (float(t) for t in s.replace(",", " ").split()[:2])
        return x, y
    except Exception:
        print("  格式不對, 略過這點")
        return None


def print_points(pixels, arms):
    """把點位印成可直接貼進 affine_transform.py 的清單。"""
    if not pixels:
        print("  目前沒有任何點")
        return
    print("\n===== 貼進 affine_transform.py 的「學生作答區」 =====")
    print("PIXELS = [")
    for cx, cy in pixels:
        print(f"    ({cx:.1f}, {cy:.1f}),")
    print("]\nARMS = [")
    for X, Y in arms:
        print(f"    ({X:.1f}, {Y:.1f}),")
    print("]\n" + "=" * 52)


def main():
    try:
        profiles = load_profiles(PROFILES_FILE)
        print(f"[sample] 已載入 {PROFILES_FILE}: "
              f"{', '.join(p.name for p in profiles)} (任一件 b 物件都可當基準)")
    except Exception:
        print(f"[sample] 找不到 {PROFILES_FILE} → 先跑 vision_tuner.py 按 s 存 profile")
        return

    cap = cam.open_camera()
    if cap is None:
        print("[sample] 開不了相機")
        return
    print(__doc__)

    pixels, arms = [], []
    locked_px = None            # 鎖定的像素; 非 None 時凍結偵測
    last_mask = None
    win = "affine_sample (SPACE=lock, c=enter X,Y)"
    # 兩個視窗都要先用 WINDOW_NORMAL 建好: 沒有 namedWindow 就直接 imshow 會變成 WINDOW_AUTOSIZE,
    # 那種視窗大小被圖片鎖死, 使用者拖邊框也改不了
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.namedWindow("mask", cv2.WINDOW_NORMAL)

    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        view = frame.copy()
        objs = []

        if locked_px is None:                       # 未鎖定: 正常偵測
            objs, masks = detect_with_profiles(frame, profiles)
            last_mask = next(iter(masks.values())) if masks else None
            cur = objs[0] if objs else None         # 面積最大者
            if cur is not None:
                cx, cy = int(round(cur["cx"])), int(round(cur["cy"]))
                cv2.drawMarker(view, (cx, cy), (0, 0, 255), cv2.MARKER_CROSS, 22, 2)
                cv2.putText(view, f"px=({cx},{cy})", (cx + 10, cy - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            hint = "SPACE=lock"
        else:                                       # 已鎖定: 凍結偵測
            cur = None
            cx, cy = locked_px
            cv2.drawMarker(view, (cx, cy), (255, 255, 0), cv2.MARKER_CROSS, 26, 2)
            cv2.putText(view, f"LOCKED ({cx},{cy})  bring ARM here",
                        (cx + 12, cy - 12), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (255, 255, 0), 2)
            hint = "c=enter X,Y  x=unlock"

        for (pcx, pcy) in pixels:                   # 已完成的點畫綠圈
            cv2.circle(view, (int(pcx), int(pcy)), 6, (0, 255, 0), 2)
        cv2.putText(view, f"samples={len(pixels)}  {hint}  u=undo p=print q=quit",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.imshow(win, view)
        if last_mask is not None:
            cv2.imshow("mask", last_mask)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break
        elif key == ord(' '):
            if cur is None:
                print("  沒偵測到物件, 無法鎖定" if locked_px is None else "  已是鎖定狀態")
            else:
                locked_px = (int(round(cur["cx"])), int(round(cur["cy"])))
                print(f"  已鎖定 {locked_px}, 把手臂 Jog 到這一點")
        elif key == ord('x') and locked_px is not None:
            locked_px = None
            print("  已解除鎖定")
        elif key == ord('c'):
            if locked_px is None:
                print("  先按 SPACE 鎖定, 再按 c")
                continue
            axy = _ask_arm_xy()
            if axy is None:
                continue
            pixels.append((float(locked_px[0]), float(locked_px[1])))
            arms.append(axy)
            locked_px = None
            print(f"  第 {len(pixels)} 點完成: 像素{pixels[-1]} ↔ 手臂{axy}")
        elif key == ord('u') and pixels:
            pixels.pop(); arms.pop()
            print(f"  刪掉上一點, 剩 {len(pixels)} 點")
        elif key == ord('p'):
            print_points(pixels, arms)

    print_points(pixels, arms)      # 離開前再印一次, 避免忘了抄
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
