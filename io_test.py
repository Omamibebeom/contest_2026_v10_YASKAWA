"""
io_test.py —— 賽前測試 放置板物件 (a 通道) 顏色 → IO 訊號 (接線、手臂解碼表)

畫面顯示: 目前看到的顏色 (只看 IO_CODES 裡的顏色, 取面積最大者)、ready 腳電位、a 通道狀態。
手臂拉高 ready 時會和比賽一樣自動投票 VOTE_SEC 秒再送出 IO 訊號 (用的就是 main_contest.ChannelA),
所以 io_test 測過的「ready → 訊號」迴路, 比賽時行為完全相同。
鍵位:
  1~9   送出 IO_CODES 裡第 1~9 個顏色的訊號 (不看相機, 純測接線)
  f     送出失敗碼
  0     全部繼電器關閉
  r     把目前看到的顏色送出去 (和比賽動作一樣)
  q     離開

改訊號: 改 pi_gpio_controller.py 頂端的 IO_CODES。
改顏色: 用 vision_tuner.py。
"""
import cv2

import camera_config as cam
from color_detect import load_profiles, detect_with_profiles
from pi_gpio_controller import PiGPIOController, IO_CODES, FAIL_CODE
from main_contest import ChannelA     # 沿用比賽的 ready → 投票 → 送 IO 狀態機 (import 不會開相機或 socket)

PROFILES_FILE = "vision_profiles.json"


def main():
    profiles = load_profiles(PROFILES_FILE)
    a_profiles = [p for p in profiles if p.name in IO_CODES]
    names = list(IO_CODES)
    print(__doc__)
    print("[io] 數字鍵對應:")
    for i, n in enumerate(names, start=1):
        print(f"      {i} = {n}  R2 R3 R4 = {IO_CODES[n]}")
    print(f"      f = 失敗碼  R2 R3 R4 = {FAIL_CODE}")
    missing = [n for n in names if n not in [p.name for p in profiles]]
    if missing:
        print(f"[io] 注意: IO_CODES 的 {missing} 在 {PROFILES_FILE} 裡沒有, 先用 vision_tuner.py 存")

    gpio = PiGPIOController()
    cap = cam.open_camera()
    if cap is None:
        print("[io] 開不了相機")
        gpio.cleanup()
        return

    last = "-"
    a = ChannelA(gpio, profiles)        # ready 拉高就自動辨識並送訊號
    # 先用 WINDOW_NORMAL 建視窗, 使用者才能拖邊框改大小 (直接 imshow 會變成不能改的 AUTOSIZE)
    cv2.namedWindow("io_test", cv2.WINDOW_NORMAL)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            a.step(frame)                               # 手臂拉 ready → 自動投票 → 送 IO
            objs, _ = detect_with_profiles(frame, a_profiles)
            seen = objs[0]["name"] if objs else None

            view = frame.copy()
            if objs:                                    # 標出最大那件
                o = objs[0]
                cv2.drawContours(view, [o["contour"]], -1, (0, 220, 0), 2)
                cv2.putText(view, o["name"], (int(o["cx"]) + 8, int(o["cy"]) - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 0), 2)
            cv2.putText(view, f"seen={seen}   ready={gpio.ready()} [{a.state}]   last IO: {last}",
                        (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.putText(view, "1-9=send color  f=fail  0=off  r=send seen  q=quit",
                        (8, view.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            cv2.imshow("io_test", view)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                break
            elif ord('1') <= key <= ord('9') and key - ord('1') < len(names):
                last = names[key - ord('1')]
                gpio.send(last)
            elif key == ord('f'):
                last = "FAIL"
                gpio.send_fail()
            elif key == ord('0'):
                last = "off"
                gpio.all_off()
            elif key == ord('r'):
                if seen:
                    last = seen
                    gpio.send(seen)
                else:
                    last = "FAIL"
                    gpio.send_fail()
    finally:
        cap.release()
        gpio.cleanup()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
