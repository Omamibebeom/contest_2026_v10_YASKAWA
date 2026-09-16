"""
main_contest.py —— 比賽主程式 (跑在樹莓派)

兩個通道 (一句話: a 是「這是什麼顏色」, b 是「這個顏色在哪裡」):
  a 通道 (放置板):        手臂從放置板夾起指定物件、舉到鏡頭前 → 程式辨識顏色
                          → 用 IO 訊號告訴手臂是哪個顏色 → 手臂決定放到哪一區
  b 通道 (隨機位置放置板): 程式開場拍快照, 算出每件物件的手臂座標 → 手臂要下一件座標
                          → 程式照顏色順序回一件的座標 → 手臂去夾
                          (手臂「怎麼要、怎麼收」由 arm_link.py 決定, 四家手臂各有一版; 本檔四家相同)

賽前準備 (照順序):
  1. vision_tuner.py        調每個顏色的 HSV, 存進 vision_profiles.json
  2. affine_sample_tool.py  取像素↔手臂點位, 抄進 affine_transform.py
  3. io_test.py             確認 顏色 → IO 訊號 的接線
  4. 填好下面的 PICK_ORDER (pi_gpio_controller.py 的 IO_CODES 也要填)

執行:
  python3 main_contest.py              有畫面 (練習用)
  python3 main_contest.py --no-ui      正式比賽
  再加 --practice                      練習模式: PICK_ORDER 用完自動從頭再來

啟動後先拍快照 (手臂勿在畫面內), 終端印出「階段二」(以及 arm_link 的連線訊息, 若有) 之後才按手臂。
有畫面時的熱鍵: r = 重拍快照   c = 取用順序歸零   q = 離開
"""
import time
import argparse
from collections import Counter

import cv2

import camera_config as cam
import arm_link
from color_detect import load_profiles, detect_with_profiles, biggest_color
from affine_transform import pixel_to_arm
from pi_gpio_controller import PiGPIOController, IO_CODES

# ======= 學生作答區: 隨機位置放置板上物件的夾取順序 (b 通道, 填顏色名) =======
# 手臂每要一次座標就給下一個顏色; 同色兩件就寫兩次 (畫面由左到右給)。
# 顏色名要和 vision_profiles.json 存的名稱一樣 (小寫)。
PICK_ORDER = ["red", "blue", "green"]
# ================================================================

PROFILES_FILE = "vision_profiles.json"
WARMUP_FRAMES = 15          # 拍快照前先丟掉的幀數, 等相機曝光穩定
VOTE_SEC = 3.0              # a 通道 (放置板物件): ready 拉高後投票幾秒


class ChannelA:
    """a 通道 (放置板物件舉到鏡頭前): ready 拉高 → 投票 VOTE_SEC 秒 → 送 IO 訊號。"""

    def __init__(self, gpio, profiles):
        self.gpio = gpio
        self.profiles = profiles
        self.state = "WAIT_READY"       # WAIT_READY → VOTING → WAIT_RELEASE
        self.t0 = 0
        self.votes = Counter()
        self.note = ""                  # 畫面顯示用

    def step(self, frame):
        """每一幀呼叫一次, 依狀態做一小步。"""
        ready = self.gpio.ready()

        if self.state == "WAIT_RELEASE":        # 送完 IO 後, 等手臂把 ready 放下才收下一件
            if ready == 0:
                self.state = "WAIT_READY"
            return

        if self.state == "WAIT_READY":
            if ready == 1:
                self.state = "VOTING"
                self.t0 = time.time()
                self.votes.clear()
                print(f"[a] 收到 ready, 投票 {VOTE_SEC} 秒")
            return

        # VOTING: 每一幀投一票給看到的顏色
        color = biggest_color(frame, self.profiles, IO_CODES)
        if color:
            self.votes[color] += 1
        self.note = f"votes={dict(self.votes)}"
        if time.time() - self.t0 < VOTE_SEC:
            return
        if self.votes:
            color, n = self.votes.most_common(1)[0]
            print(f"[a] 判定 {color} ({n} 票) → 送 IO")
            self.gpio.send(color)
        else:
            print("[a] 沒看到任何 IO_CODES 裡的顏色 → 送失敗碼")
            self.gpio.send_fail()
        self.state = "WAIT_RELEASE"


class ChannelB:
    """b 通道 (隨機位置放置板): 開場拍一張快照算好每件的座標, 之後手臂每要一次座標 (arm_link 轉成 GET) 就查表回座標。"""

    def __init__(self, cap, profiles, practice):
        self.cap = cap
        self.profiles = profiles
        self.practice = practice
        self.items = []             # 每件: x, y (手臂座標), color, cx, cy (像素), served
        self.order_i = 0            # PICK_ORDER 用到第幾個

    def take_snapshot(self):
        for _ in range(WARMUP_FRAMES):
            self.cap.read()
        _ok, frame = self.cap.read()
        objs, _ = detect_with_profiles(frame, self.profiles)
        objs.sort(key=lambda o: o["cx"])            # 由左到右
        self.items = []
        for o in objs:
            x, y = pixel_to_arm(o["cx"], o["cy"])
            self.items.append({"x": x, "y": y, "color": o["name"],
                               "cx": o["cx"], "cy": o["cy"], "served": False})
        self.order_i = 0
        print(f"[b] 快照完成, 共 {len(self.items)} 件:")
        for i, s in enumerate(self.items):
            print(f"    #{i} {s['color']:8s} 像素({s['cx']:.0f},{s['cy']:.0f}) → 手臂({s['x']:.1f},{s['y']:.1f})")
        for c in PICK_ORDER:                        # 賽前就能發現顏色名寫錯
            if not any(s["color"] == c for s in self.items):
                print(f"[b] 注意: PICK_ORDER 有 '{c}', 但快照裡沒有這個顏色")

    def reset(self):
        """取用順序歸零, 全部視為還沒給過。"""
        self.order_i = 0
        for s in self.items:
            s["served"] = False

    def handle(self, cmd):
        """處理 arm_link 轉來的指令字, 回傳要回的回覆 (送到手臂的格式由 arm_link 決定)。"""
        if cmd == arm_link.CMD_GET:
            if self.order_i >= len(PICK_ORDER):
                if not self.practice:
                    print("[b] PICK_ORDER 用完 → NONE")
                    return arm_link.REPLY_NONE
                print("[b] (練習) PICK_ORDER 用完 → 從頭再來")
                self.reset()
            color = PICK_ORDER[self.order_i]
            self.order_i += 1                       # 不論找不找得到都前進, 手臂才不會卡在同一件
            for s in self.items:
                if s["color"] == color and not s["served"]:
                    s["served"] = True
                    print(f"[b] 給 {color} → 手臂({s['x']:.1f},{s['y']:.1f})")
                    return arm_link.reply_target(s["x"], s["y"])   # 只回座標, 不回顏色
            print(f"[b] 沒有還沒給過的 '{color}' → NONE")
            return arm_link.REPLY_NONE
        if cmd == arm_link.CMD_SCAN:
            return arm_link.reply_count(len(self.items))
        if cmd == arm_link.CMD_RESET:
            self.reset()
            return arm_link.REPLY_OK
        if cmd == arm_link.CMD_QUIT:
            return arm_link.REPLY_BYE
        return arm_link.REPLY_OK                    # GRIP / RELEASE: 回 OK 就好


def draw(frame, a, b):
    """練習畫面: 快照裡的每件 + 狀態列。"""
    view = frame.copy()
    for i, s in enumerate(b.items):
        c = (120, 120, 120) if s["served"] else (0, 220, 0)
        p = (int(s["cx"]), int(s["cy"]))
        cv2.drawMarker(view, p, c, cv2.MARKER_CROSS, 16, 2)
        cv2.putText(view, f"#{i}{s['color']}", (p[0] + 8, p[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 2)
    nxt = PICK_ORDER[b.order_i] if b.order_i < len(PICK_ORDER) else "-"
    cv2.putText(view, f"A:{a.state} {a.note}    B: next={nxt}", (8, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(view, "r=re-snapshot  c=reset  q=quit", (8, view.shape[0] - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    return view


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-ui", action="store_true", help="不開畫面 (正式比賽)")
    parser.add_argument("--practice", action="store_true", help="練習模式: PICK_ORDER 用完自動從頭再來")
    args = parser.parse_args()

    try:
        profiles = load_profiles(PROFILES_FILE)
    except FileNotFoundError:
        print(f"[main] 找不到 {PROFILES_FILE} → 先跑 vision_tuner.py 存顏色")
        return
    print(f"[main] 顏色: {[p.name for p in profiles]}  夾取順序: {PICK_ORDER}  IO 顏色: {list(IO_CODES)}")

    gpio = PiGPIOController()
    cap = cam.open_camera()
    if cap is None:
        print("[main] 開不了相機")
        gpio.cleanup()
        return

    a = ChannelA(gpio, profiles)
    b = ChannelB(cap, profiles, args.practice)
    link = arm_link.ArmLink()
    try:
        print("[main] 階段一: 拍快照 (手臂勿在畫面內)")
        b.take_snapshot()
        link.open()                                 # 快照完成才開始和手臂講話
        print(f"[main] === 階段二: 可以按手臂了 ({arm_link.HOST}:{arm_link.PORT})"
              + ("  [練習模式]" if args.practice else "") + " ===")

        if not args.no_ui:
            # 先用 WINDOW_NORMAL 建視窗, 使用者才能拖邊框改大小 (直接 imshow 會變成不能改的 AUTOSIZE)
            cv2.namedWindow("contest", cv2.WINDOW_NORMAL)
        running = True
        while running:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.02)
                continue
            a.step(frame)                           # a 通道: 放置板物件的顏色
            for cmd in link.poll():                 # b 通道: 隨機板物件的座標
                link.send(b.handle(cmd))
                if cmd == arm_link.CMD_QUIT:
                    running = False
            if args.no_ui:
                continue
            cv2.imshow("contest", draw(frame, a, b))
            key = cv2.waitKey(1) & 0xFF
            if key == ord('r'):
                b.take_snapshot()
            elif key == ord('c'):
                b.reset()
            elif key in (ord('q'), 27):
                running = False
    finally:
        link.close()
        cap.release()
        gpio.cleanup()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
