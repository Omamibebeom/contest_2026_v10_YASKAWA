"""
camera_config.py —— 開相機 (所有程式共用)

插上相機直接跑, 程式會自己從 0 號往上找, 真的讀到畫面才算找到。
兩台相機都接著、想指定用哪一台: 把 FORCE_INDEX 改成那個編號。
畫面卡卡的可以試 USE_MJPG = True (C270 用 MJPG 格式幀率高很多; 畫面不正常就改回 False)。
"""
import sys
import cv2

FORCE_INDEX = None                          # None = 自動找; 例如 2 = 只用 2 號
SEARCH_RANGE = range(0, 6)                  # 自動找的範圍 0~5
FRAME_WIDTH, FRAME_HEIGHT = 1280, 720       # 所有程式都用這個解析度, 像素座標才對得上
USE_MJPG = False                            # True = 要求相機用 MJPG 格式 (幀率較高)

CAMERA_BACKEND = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY


def open_camera():
    """回傳開好的相機; 找不到回傳 None。"""
    indexes = [FORCE_INDEX] if FORCE_INDEX is not None else list(SEARCH_RANGE)
    for idx in indexes:
        cap = cv2.VideoCapture(idx, CAMERA_BACKEND)
        if USE_MJPG:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

        ok = False
        for _ in range(3):                  # 有些相機第一幀會失敗, 多試兩次
            ok, _frame = cap.read()
            if ok:
                break
        if not ok:
            cap.release()
            continue

        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[camera] index {idx} 開啟, 解析度 {w}x{h}")
        if (w, h) != (FRAME_WIDTH, FRAME_HEIGHT):
            print(f"[camera] 注意: 不是 {FRAME_WIDTH}x{FRAME_HEIGHT}, affine 的取樣點位會對不上")
        return cap

    print(f"[camera] 試過 {indexes} 都讀不到畫面 (相機沒插? Linux 用 ls /dev/video* 看)")
    return None
