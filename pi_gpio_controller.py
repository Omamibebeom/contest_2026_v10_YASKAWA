"""
pi_gpio_controller.py —— 用 4 顆繼電器把「顏色」變成手臂看得懂的訊號

訊號規則 (手臂端照這個解碼):
  1. R2 R3 R4 先擺好 3 位編碼
  2. 等 1 秒
  3. R1 拉高 (代表「可以讀了」), 保持 HOLD_SEC 秒
  4. 全部關閉
辨識失敗: R1 不拉高, R2 R3 R4 = FAIL_CODE, 保持 FAIL_HOLD_SEC 秒

不在樹莓派上跑時自動變成「模擬模式」: 只印字, 不動硬體。
"""
import time
import threading

# ======= 學生作答區: 放置板物件 (a 通道) 顏色 → IO 訊號 =======
# 顏色名要和 vision_profiles.json 存的名稱一樣 (小寫)
# 值是 (R2, R3, R4), 1 = 開, 0 = 關
IO_CODES = {
    "red":   (0, 0, 1),
    "blue":  (0, 1, 0),
    "green": (0, 1, 1),
}
FAIL_CODE = (1, 1, 1)        # 辨識失敗時的 R2 R3 R4 (R1 不拉高); 
HOLD_SEC = 7                 # R1 拉高後保持幾秒
FAIL_HOLD_SEC = 10           # 失敗碼保持幾秒 (要比手臂等 R1 的逾時更久)
# ==========================================================

RELAY_PINS = [17, 27, 22, 23]   # R1 R2 R3 R4 接的 GPIO (BCM 編號)
READY_PIN = 26                  # 手臂 DO → 這支腳; 拉高 = 請開始辨識
INVERSE_LOGIC = True

try:
    import RPi.GPIO as GPIO
    HAVE_GPIO = True
except (ImportError, RuntimeError):
    HAVE_GPIO = False
    print("[gpio] 沒有 GPIO 函式庫 → 模擬模式 (只印字, 不動硬體)")


class PiGPIOController:
    def __init__(self):
        self.sim_ready = 0              # 模擬模式時 ready 腳的假值 (測試程式可以改它)
        if not HAVE_GPIO:
            return
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for pin in RELAY_PINS:
            GPIO.setup(pin, GPIO.OUT)
        GPIO.setup(READY_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)   # 沒接線時穩定讀 0
        self.all_off()

    def _set(self, r1, r2, r3, r4):
        """直接設定四顆繼電器 (1 = 開)。"""
        if not HAVE_GPIO:
            print(f"[gpio] R1 R2 R3 R4 = {r1} {r2} {r3} {r4}")
            return
        for pin, on in zip(RELAY_PINS, (r1, r2, r3, r4)):
            if INVERSE_LOGIC:
                GPIO.output(pin, GPIO.LOW if on else GPIO.HIGH)
            else:
                GPIO.output(pin, GPIO.HIGH if on else GPIO.LOW)

    def all_off(self):
        self._set(0, 0, 0, 0)

    def send(self, color):
        """送出某個顏色的訊號 (背景執行, 不卡主程式)。顏色不在 IO_CODES 裡就送失敗碼。"""
        if color not in IO_CODES:
            self.send_fail()
            return
        r2, r3, r4 = IO_CODES[color]

        def run():
            print(f"[gpio] {color} → R2 R3 R4 = {r2} {r3} {r4}; 1 秒後 R1 拉高, 保持 {HOLD_SEC} 秒")
            self._set(0, r2, r3, r4)
            time.sleep(1)
            self._set(1, r2, r3, r4)
            time.sleep(HOLD_SEC)
            self.all_off()

        threading.Thread(target=run).start()

    def send_fail(self):
        """送出辨識失敗碼 (背景執行)。"""
        r2, r3, r4 = FAIL_CODE

        def run():
            print(f"[gpio] 辨識失敗 → R2 R3 R4 = {r2} {r3} {r4}, R1 不拉高, 保持 {FAIL_HOLD_SEC} 秒")
            self._set(0, r2, r3, r4)
            time.sleep(FAIL_HOLD_SEC)
            self.all_off()

        threading.Thread(target=run).start()

    def ready(self):
        """讀 ready 腳: 1 = 手臂請我們辨識。"""
        if not HAVE_GPIO:
            return self.sim_ready
        return GPIO.input(READY_PIN)

    def cleanup(self):
        """程式結束前: 全部關閉、釋放腳位。"""
        if HAVE_GPIO:
            self.all_off()
            GPIO.cleanup()
