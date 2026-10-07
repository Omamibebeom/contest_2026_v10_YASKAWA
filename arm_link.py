"""
arm_link.py —— 樹莓派 ↔ 安川 YRC1000 手臂通訊

兩條路同時開, 手臂端用哪一條都可以 (主程式與 io_test.py 都不用改):
  a 通道 (顏色): 繼電器 GPIO 照常送; 同一時序再多寫一份到 Modbus TCP (埠 502)。
                 安川端用接線讀或用網路讀都可以; ready 也是兩邊擇一: GPIO26 拉高 或 外部輸出 #30030 為 ON
  b 通道 (座標): High Speed Ethernet Server (UDP 埠 10040, 直接寫 P001 / P002 / B003; 任何模式都能用, 不需 REMOTE);
                 另外也接受 Modbus 的請求 (外部輸出 #30031), 把座標寫進 M 暫存器、以外部輸入 #20034 回覆

b 通道怎麼運作 (High Speed Ethernet Server 那條路)
  手臂 job 把 B001 設成 1 (= 我要座標)
  → 本程式讀回 P001 現值, 只換 X Y Z 再寫回 (夾取點 Z = Z_PICK); 用同一筆資料換 Z = Z_SAFE 寫進 P002 (正上方)
    座標系 / 姿態 (form) / Tool / User frame 全部沿用 P001 現值, 所以賽前要先在 pendant 把 P001 教成直角座標的夾取姿態點
  → 寫 B003: 0 = 有座標, 1 = 沒座標 (該顏色已給完或 PICK_ORDER 用完, 這件跳過)
  → 最後把 B001 設回 0 (= 寫好了)
  → job 看到 B001 變 0, 先判 B003, 再讀 P002 / P001 去夾
  變數編號固定: B001 旗標 / B003 狀態 / P001 夾取點 / P002 正上方 (job 端要用同樣的編號)

b 通道怎麼運作 (Modbus 那條路; 和上面二選一, 兩條同時開著)
  手臂 job 把外部輸出 #30031 設 ON (= 我要座標)
  → 本程式寫 M010 = X × 10, M011 = Y × 10 (單位 0.1 mm, 16-bit 有號數; 負值以二補數寫入)
    M012 = 0 有座標 / 1 沒座標 (該顏色已給完或 PICK_ORDER 用完, 這件跳過)
  → 再把外部輸入 #20034 設 ON (= 寫好了)
  → job 看到 #20034 ON, 先判 M012, 再 GETREG 讀 M010 / M011、SETE 填進位置變數去夾 (寫法見 docs/yaskawa_job_interface.txt)
  → job 讀完把 #30031 設 OFF → 本程式把 #20034 放 OFF, 等下一次
  Z 高度、姿態、座標系由 job 自己的常數決定 (High Speed Ethernet Server 那條路是本程式代填 Z_PICK / Z_SAFE)

a 通道怎麼運作 (時序、編碼、保持秒數全部照 pi_gpio_controller.py, 本檔只是「同時多送一份」)
  本檔在 import 時把 pi_gpio_controller.PiGPIOController 的 ready / send / send_fail / all_off / cleanup
  換成「GPIO + Modbus 一起做」的版本; 學生作答的 IO_CODES / FAIL_CODE / HOLD_SEC 照常從那裡讀。
  Modbus 位址 (實機已驗證: 外部輸入 #20030 起 ↔ coil 0 起, 外部輸出 #30030 起 ↔ discrete input 0 起, M000 ↔ holding register 0):
    繼電器 R1 R2 R3 R4  →  外部輸入 #20030 #20031 #20032 #20033  (coil 0~3, 每次整塊 64 bit 寫)
    ready               ←  外部輸出 #30030                       (discrete input 0)
    另外 M000 = 顏色數字碼 (R2*4 + R3*2 + R4; 預設 red=1 blue=2 green=3, 失敗碼 7), job 想讀整數時用
    b 通道: 要座標 ← 外部輸出 #30031 (discrete input 1); 座標 → M010 M011 M012; 寫好了 → 外部輸入 #20034 (coil 4)
  Modbus 連不上 (安川沒開 Modbus 選項、或只接繼電器) 時, GPIO 照常, 終端印一次提示, 不影響比賽。

賽前要做的 (下面「賽前設定」區; Z 高度要在安川實機上量, 不能沿用別台手臂的數字)
  1. HOST                         安川控制器的 IP (High Speed Ethernet Server 與 Modbus 共用同一個 IP)
  2. pendant 上把手臂 Jog 到「夾取姿態、剛好碰到物件」的點, 教成 P001 (直角座標; 座標系要和 affine 取樣時 pendant 顯示的一樣)
                                  再跑  python3 arm_link.py --read-p 1  看讀回的 X Y Z 是否和 pendant 一致 (確認單位換算)
  3. Z_PICK / Z_SAFE              夾取高度 / 安全通過高度, 量出來填
  4. MODBUS_ENABLE                不用 Modbus 就設 False (a 通道只走繼電器, b 通道只走 High Speed Ethernet Server)

安川控制器要先開 (老師賽前確認)
  - High Speed Ethernet Server 功能 (UDP 埠 10040); 不需要 command remote, pendant 任何模式都可以
  - 要用 Modbus 的話: 控制器的 Modbus TCP (CPU Board) 選項

單獨測試 (不開相機)
  python3 arm_link.py                 手動輸入座標; 每次 job 把 B001 設 1 就拿到目前這一組
  python3 arm_link.py --read-p 1      讀回 P001 的全部欄位與換算後的 mm / 度, 和 pendant 對照
  python3 arm_link.py --host 192.168.0.1   臨時指定 IP (不改檔)
  python3 modbus_test_yaskawa.py      Modbus 那條路: 自我檢查、手動送 a 通道訊號; --coord 模擬 b 通道回座標

主程式怎麼用 (main_contest.py 已寫好, 這裡只是說明)
  link = ArmLink(); link.open()
  每一圈:  for cmd in link.poll(): link.send(b.handle(cmd))
  結束:    link.close()
"""
import time
import queue
import argparse
import threading

import pi_gpio_controller
from pi_gpio_controller import IO_CODES, FAIL_CODE, HOLD_SEC, FAIL_HOLD_SEC

# ======================= 賽前設定 (只改這一區) =======================
HOST = "192.168.0.1"      # 安川控制器 IP
PORT = 10040                # High Speed Ethernet Server 的機器人控制埠 (UDP), 不用改

Z_PICK = 20.0               # 夾取高度 (mm)
Z_SAFE = 50.0               # 安全通過高度 (mm)
WRITE_APPROACH = True       # False = 不寫 P002 (job 自己用相對移動下降時可關)
MODBUS_ENABLE = True        # 是否開 Modbus 那條路 (a 通道同時送、b 通道接受 #30031 請求); False = 只走繼電器 + High Speed Ethernet Server
# =====================================================================

# ---------- 固定的變數編號 (job 端照這個寫; 不開放修改) ----------
FLAG_VAR = 1                # B001: job 寫 1 = 要座標; 樹莓派寫 0 = 寫好了
STATUS_VAR = 3              # B003: 0 = 有座標, 1 = 沒座標
PICK_P = 1                  # P001: 夾取點 (賽前要先教成直角座標的夾取姿態點; 寫入時只換 X Y Z)
ABOVE_P = 2                 # P002: 夾取點正上方 (用 P001 的資料換 Z 寫入)
ST_OK, ST_NONE = 0, 1

# ---------- High Speed Ethernet Server 的位置資料單位 (手冊: 直角座標 0.001 mm, 角度 0.0001 度; 用 --read-p 對照 pendant 確認) ----------
POS_UNIT_MM = 1000          # 位置變數的 X Y Z 整數值 = mm × 1000
POS_UNIT_DEG = 10000        # Rx Ry Rz 整數值 = 度 × 10000
HSES_TIMEOUT = 0.8          # 每個 UDP 請求等回覆最多幾秒
POS_DATA_TYPE_NAMES = {0: "脈衝 (pulse)", 16: "Base", 17: "Robot", 18: "User", 19: "Tool"}   # 位置變數的 data_type 欄位

POLL_SEC = 0.3              # 每隔幾秒問一次 B001
RETRY_SEC = 1.0             # 通訊失敗後隔幾秒再試
REPLY_WAIT_SEC = 5.0        # 等主程式算回覆最多幾秒 (正常不到 0.1 秒)

# ---------- 主程式用的指令字與回覆 ----------
CMD_GET = "GET"             # 手臂要座標 (B001 = 1 時由本程式產生)
CMD_SCAN = "SCAN"           # 以下五個本程式不會產生, 保留給主程式的 handle() 使用
CMD_GRIP = "GRIP"
CMD_RELEASE = "RELEASE"
CMD_RESET = "RESET"
CMD_QUIT = "QUIT"

REPLY_OK = {"kind": "ok"}
REPLY_BYE = {"kind": "bye"}
REPLY_NONE = {"kind": "none"}       # 沒座標 → 寫 B003 = 1


def reply_target(x, y):
    """一件物件的手臂座標 (會被寫進 P001 / P002)。"""
    return {"kind": "target", "x": float(x), "y": float(y)}


def reply_count(n):
    return {"kind": "count", "n": int(n)}


class ArmLink:
    """主程式只碰這四個方法: open() / poll() / send() / close()。

    背景執行緒負責問安川「B001 是 1 了沒」; 是 1 就把 GET 丟進佇列給主程式,
    等主程式 send() 回覆, 再把回覆寫進安川變數。通訊都在執行緒裡, 不會卡住主迴圈。
    """

    def __init__(self):
        self._cmds = queue.Queue()      # 執行緒 → 主程式: 手臂要座標了
        self._replies = queue.Queue()   # 主程式 → 執行緒: 算好的回覆
        self._stop = threading.Event()
        self._thread = None
        self._arm = None
        self.state = "INIT"             # INIT / POLL / SERVE / ERROR (_set() 變化時印到終端)
        self.note = ""                  # 最近一句訊息 (_set() 變化時印到終端)
        self.served = 0                 # 已經給出去幾件 (兩條路合計)
        # Modbus 那條路 (b 通道)
        self._mb_asking = False         # True = 這次 #30031 已轉成 GET 交給主程式, 別重複交
        self._pending = []              # 每個交出去的 GET 記下來源 ("eth" / "mb"), send() 照順序回給正確的那一邊

    def open(self):
        """開始和手臂講話 (主程式在快照完成後才呼叫)。馬上回來, 連線在背景進行。"""
        self._arm = _Yaskawa(HOST, PORT)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if MODBUS_ENABLE:
            _mb.start_poller()
            print(f"[arm] High Speed Ethernet Server {HOST}:{PORT} (B001) 與 Modbus {HOST}:{MODBUS_PORT} (#30031) 兩條路都在等 job 要座標")

    def _poll_modbus(self):
        """#30031 剛設 ON 且還沒回過 → 回 ["GET"]; #30031 是 OFF → 順便把 #20034 放下。只讀快取, 不碰網路。"""
        if not MODBUS_ENABLE or not _mb.alive:
            return []
        if _mb.coord_req:
            if not self._mb_asking and not _mb.coord_ack:
                self._mb_asking = True
                return [CMD_GET]
        elif self._mb_asking or _mb.coord_ack:
            if _mb.set_coil(MB_COIL_COORD_ACK, False):      # job 放下 #30031 = 這輪結束 → 放下 #20034
                self._mb_asking = False
        return []

    def poll(self):
        """收這一圈的指令, 回傳清單 (可能是空的)。High Speed Ethernet Server (B001) 與 Modbus (#30031) 兩邊都看, 記下每個 GET 的來源。"""
        cmds = []
        while True:
            try:
                cmds.append(self._cmds.get_nowait())
                self._pending.append("eth")
            except queue.Empty:
                break
        for cmd in self._poll_modbus():
            cmds.append(cmd)
            self._pending.append("mb")
        return cmds

    def send(self, reply):
        """把主程式算好的回覆回給剛才那個要座標的來源:
        High Speed Ethernet Server → 交給背景執行緒寫 P001 / P002 / B003 / B001
        Modbus          → 寫 M010 / M011 / M012, 再把 #20034 設 ON (資料先寫成功才拉 ACK)"""
        src = self._pending.pop(0) if self._pending else "eth"
        if src == "eth":
            self._replies.put(reply)
            return
        if reply.get("kind") == "target":
            ok = _mb.write_coord(reply["x"], reply["y"], 0)
            note = f"M010/M011 = ({reply['x']:.1f},{reply['y']:.1f}) × {COORD_SCALE}, M012=0"
        else:
            ok = _mb.write_coord(0.0, 0.0, 1)
            note = "沒有座標可給 → M012=1 (job 跳過這件)"
        if ok and _mb.set_coil(MB_COIL_COORD_ACK, True):
            self.served += 1
            print(f"[arm] 第 {self.served} 件 (Modbus) → {note}, #20034 ON")
        else:
            print(f"[arm] Modbus 寫入失敗: {note}")

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._arm is not None:
            self._arm.close()

    # ---------------- 以下在背景執行緒跑 ----------------
    def _set(self, state, note=""):
        if state != self.state or note != self.note:
            self.state, self.note = state, note
            if note:
                print(f"[arm] {note}")

    def _write_reply(self, reply):
        """把回覆寫進安川變數。順序固定 P001 → P002 → B003 → B001=0,
        所以 job 看到 B001 變 0 時, 其他變數一定已經是這一輪的新值。
        P001 / P002 只換 X Y Z, 座標系 / 姿態 / Tool 沿用 P001 現值 (賽前教好的夾取姿態點)。"""
        if reply.get("kind") == "target":
            rec = self._arm.write_position(PICK_P, reply["x"], reply["y"], Z_PICK)        # 讀 P001 現值 → 換 X Y Z → 寫回
            if WRITE_APPROACH:
                self._arm.write_position(ABOVE_P, reply["x"], reply["y"], Z_SAFE, template=rec)   # P002 沿用 P001 的姿態/座標系
            self._arm.write_byte(STATUS_VAR, ST_OK)
            self.served += 1
            self._set("SERVE", f"第 {self.served} 件 → P{PICK_P:03d}({reply['x']:.1f},{reply['y']:.1f})")
        else:
            self._arm.write_byte(STATUS_VAR, ST_NONE)
            self._set("SERVE", f"沒有座標可給 → B{STATUS_VAR:03d}=1 (job 跳過這件)")
        self._arm.write_byte(FLAG_VAR, 0)

    def _run(self):
        while not self._stop.is_set():
            try:
                if self._arm.read_byte(FLAG_VAR) != 1:
                    self._set("POLL", "已連上安川, 等 job 把 B001 設成 1")
                    self._stop.wait(POLL_SEC)
                    continue
                self._cmds.put(CMD_GET)                 # 手臂要座標了 → 交給主程式算
                reply = None
                while reply is None and not self._stop.is_set():
                    try:
                        reply = self._replies.get(timeout=REPLY_WAIT_SEC)
                    except queue.Empty:
                        print("[arm] 主程式還沒回覆 (相機或主迴圈卡住?), 繼續等")
                if reply is None:
                    break
                self._write_reply(reply)
            except (OSError, ValueError, ArmError) as e:
                self._set("ERROR", f"{e}")
                self._stop.wait(RETRY_SEC)              # 下一圈會自動重連



# ==============================================================================
# a 通道: 繼電器 GPIO + Modbus TCP 同時送 (以下在 import 時替換 PiGPIOController 的方法)
# ==============================================================================
MODBUS_PORT = 502               # Modbus TCP 固定埠
MODBUS_ID = 1                   # Modbus unit id
MODBUS_TIMEOUT = 1.0            # 每次讀寫最多等幾秒
MODBUS_RECONNECT_SEC = 2.0      # 連線失敗後隔幾秒再試
MODBUS_POLL_SEC = 0.1           # 背景讀 ready 的週期 (主迴圈只讀快取, 不會被網路卡住)

# ---------- 位址對照 (pymodbus 位址是 0-based; 實機已驗證) ----------
MB_COIL_BITS = 64               # 外部輸入 #20030~#20100 共 8 bytes, 控制器每次整塊 64 bit 讀寫
MB_COIL_BASE = 0                # coil 0 ↔ 外部輸入 #20030
MB_COIL_R1, MB_COIL_R2, MB_COIL_R3, MB_COIL_R4 = 0, 1, 2, 3   # ↔ #20030 #20031 #20032 #20033 (同繼電器 R1~R4)
MB_DI_BASE = 0                  # discrete input 0 ↔ 外部輸出 #30030
MB_DI_READY = 0                 # ↔ #30030: 安川把它設 ON = 請樹莓派辨識 (等同 GPIO26 拉高)
MB_REG_CODE = 0                 # holding register 0 ↔ M000: 顏色數字碼 (R2*4 + R3*2 + R4), 全關時 0
# b 通道 (Modbus 那條路)
MB_DI_COORD_REQ = 1             # discrete input 1 ↔ 外部輸出 #30031: job 設 ON = 要座標
MB_COIL_COORD_ACK = 4           # coil 4 ↔ 外部輸入 #20034: 本程式設 ON = 座標已寫好
MB_REG_X = 10                   # holding register 10 ↔ M010: X × COORD_SCALE (16-bit 有號)
MB_REG_Y = 11                   # holding register 11 ↔ M011: Y × COORD_SCALE
MB_REG_STATUS = 12              # holding register 12 ↔ M012: 0 = 有座標, 1 = 沒座標
COORD_SCALE = 10                # 座標 mm × 10 取整數 (0.1 mm; ±3276.7 mm), job 端除回來 (或 × 100 變成 0.001 mm 的位置元素)


def _code_of(bits):
    """IO_CODES 的 (R2, R3, R4) → M000 的數字, R2 是最高位: (0,0,1)=1 (0,1,0)=2 (0,1,1)=3 (1,1,1)=7。"""
    r2, r3, r4 = bits
    return int(r2) * 4 + int(r3) * 2 + int(r4)


class _Modbus:
    """安川 Modbus TCP 這條路 (全檔只有一個實例 _mb)。連不上不會拋例外, 只回 False / 0 並印一次提示。

    coil 用「整塊 64 bit」寫, 所以本地留一份 shadow, 改哪一位就改 shadow 再整塊送出。
    ready 由背景執行緒每 MODBUS_POLL_SEC 讀一次存進快取, 主迴圈的 ready() 只讀快取, 網路慢也不卡畫面。
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.client = None
        self.shadow = [False] * MB_COIL_BITS
        self.ready_bit = False          # 快取: #30030 (a 通道 ready)
        self.coord_req = False          # 快取: #30031 (b 通道要座標)
        self.coord_ack = False          # 快取: #20034 (b 通道 我們拉的 ACK, 讀回來確認)
        self.alive = False              # 最近一次背景讀取成功
        self.last_fail = 0.0
        self.warned = False
        self.kw = None                  # pymodbus 的 unit id 參數名 (3.9 叫 slave, 之後叫 device_id)
        self._poller = None

    # ---------- 連線 ----------
    def _connect(self):
        """回 True = 可以讀寫。失敗後 MODBUS_RECONNECT_SEC 秒內不重試, 免得每圈都等逾時。"""
        if self.client is not None and self.client.connected:
            return True
        if time.time() - self.last_fail < MODBUS_RECONNECT_SEC:
            return False
        reason = ""
        try:
            if self.client is None:
                import inspect
                from pymodbus.client import ModbusTcpClient
                self.client = ModbusTcpClient(HOST, port=MODBUS_PORT, timeout=MODBUS_TIMEOUT, retries=0)
                params = inspect.signature(ModbusTcpClient.read_coils).parameters
                self.kw = "slave" if "slave" in params else "device_id"
            ok = self.client.connect()
        except ImportError:
            if not self.warned:
                print("[modbus] 沒有 pymodbus 套件 → a 通道只走繼電器 (pip install -r requirements_pi.txt)")
                self.warned = True
            self.last_fail = float("inf")       # 永遠不再試
            return False
        except Exception as e:
            ok, reason = False, f" ({e})"
        if ok:
            self.warned = False
            print(f"[modbus] 已連上安川 Modbus {HOST}:{MODBUS_PORT}")
            return True
        if not self.warned:
            print(f"[modbus] 連不上 {HOST}:{MODBUS_PORT}{reason} → a 通道先只走繼電器, 之後會自動重試")
            self.warned = True
        self.last_fail = time.time()
        return False

    def _call(self, name, *args, **kwargs):
        """呼叫 pymodbus 的一個讀寫方法; 任何錯誤都回 None。"""
        with self.lock:
            if not self._connect():
                return None
            try:
                kwargs[self.kw] = MODBUS_ID
                res = getattr(self.client, name)(*args, **kwargs)
            except Exception as e:
                self.last_fail = time.time()
                self.warned = False
                print(f"[modbus] {name} 失敗: {e}")
                return None
        if res is None or res.isError():
            print(f"[modbus] {name} 被安川拒絕: {res}")
            return None
        return res

    # ---------- 輸出: 繼電器 R1~R4 的狀態同步到 coil, 數字碼寫進 M000 ----------
    def set_outputs(self, r1, r2, r3, r4):
        """把四顆繼電器的目前狀態寫到安川: coil 0~3 (整塊 64 bit) + M000。"""
        if not MODBUS_ENABLE:
            return
        with self.lock:
            for idx, on in ((MB_COIL_R1, r1), (MB_COIL_R2, r2), (MB_COIL_R3, r3), (MB_COIL_R4, r4)):
                self.shadow[idx] = bool(on)
            block = list(self.shadow)
        self._call("write_coils", address=MB_COIL_BASE, values=block)
        code = _code_of((r2, r3, r4)) if (r2 or r3 or r4) else 0
        self._call("write_registers", address=MB_REG_CODE, values=[code])

    def set_coil(self, idx, on):
        """改一個 coil (經 shadow 整塊寫出, 不影響其他位); 回 True = 寫成功。"""
        with self.lock:
            self.shadow[idx] = bool(on)
            block = list(self.shadow)
        return self._call("write_coils", address=MB_COIL_BASE, values=block) is not None

    def write_coord(self, x, y, status):
        """b 通道: 寫 M010 = X×10, M011 = Y×10 (16-bit 二補數), M012 = 狀態; 回 True = 寫成功。"""
        vals = [int(round(x * COORD_SCALE)) & 0xFFFF, int(round(y * COORD_SCALE)) & 0xFFFF, int(status)]
        return self._call("write_registers", address=MB_REG_X, values=vals) is not None

    # ---------- 輸入: 背景讀 ready ----------
    def start_poller(self):
        if not MODBUS_ENABLE or self._poller is not None:
            return
        self._poller = threading.Thread(target=self._poll_loop, daemon=True)
        self._poller.start()

    def _poll_loop(self):
        while True:
            di = self._call("read_discrete_inputs", address=MB_DI_BASE, count=MB_COIL_BITS)
            co = self._call("read_coils", address=MB_COIL_BASE, count=MB_COIL_BITS)
            if di is not None and co is not None:
                self.ready_bit = bool(di.bits[MB_DI_READY])
                self.coord_req = bool(di.bits[MB_DI_COORD_REQ])
                self.coord_ack = bool(co.bits[MB_COIL_COORD_ACK])
                self.alive = True
            else:
                self.ready_bit = self.coord_req = self.coord_ack = False
                self.alive = False
            time.sleep(MODBUS_POLL_SEC)

    def close(self):
        with self.lock:
            if self.client is not None:
                try:
                    self.client.close()
                except Exception:
                    pass


_mb = _Modbus()

# ---- 保留 pi_gpio_controller 原本的方法 (GPIO 那一半), 新方法會呼叫它們 ----
_gpio_init = pi_gpio_controller.PiGPIOController.__init__
_gpio_ready = pi_gpio_controller.PiGPIOController.ready
_gpio_cleanup = pi_gpio_controller.PiGPIOController.cleanup


def _out(self, r1, r2, r3, r4):
    """四顆繼電器 + Modbus 一起設 (1 = 開)。"""
    self._set(r1, r2, r3, r4)                   # 繼電器 (pi_gpio_controller 原本的低階方法, 未被替換)
    _mb.set_outputs(r1, r2, r3, r4)             # 同一時刻寫到安川


def _a_init(self):
    """GPIO 照常初始化, 再啟動 Modbus 的 ready 背景讀取。"""
    _gpio_init(self)
    _mb.start_poller()
    if MODBUS_ENABLE:
        print("[modbus] a 通道同時走 Modbus: R1~R4 → 外部輸入 #20030~#20033, M000 = 數字碼; ready ← #30030")


def _a_ready(self):
    """GPIO26 拉高 或 安川外部輸出 #30030 為 ON, 任一個就算 ready。"""
    _mb.start_poller()                          # io_test 先建物件再 import 本檔時, __init__ 沒經過替換, 這裡補啟動
    return 1 if (_gpio_ready(self) == 1 or _mb.ready_bit) else 0


def _a_all_off(self):
    _out(self, 0, 0, 0, 0)


def _a_send(self, color):
    """時序同 pi_gpio_controller.send(): R2R3R4 擺好 → 1 秒 → R1 拉高保持 HOLD_SEC 秒 → 全關; 兩條路同步。"""
    if color not in IO_CODES:
        _a_send_fail(self)
        return
    r2, r3, r4 = IO_CODES[color]

    def run():
        print(f"[gpio+modbus] {color} → R2 R3 R4 = {r2} {r3} {r4} (M000={_code_of((r2, r3, r4))});"
              f" 1 秒後 R1 拉高, 保持 {HOLD_SEC} 秒")
        _out(self, 0, r2, r3, r4)
        time.sleep(1)
        _out(self, 1, r2, r3, r4)
        time.sleep(HOLD_SEC)
        _a_all_off(self)

    threading.Thread(target=run, daemon=True).start()


def _a_send_fail(self):
    """時序同 pi_gpio_controller.send_fail(): R1 不拉高, R2R3R4 = FAIL_CODE 保持 FAIL_HOLD_SEC 秒。"""
    r2, r3, r4 = FAIL_CODE

    def run():
        print(f"[gpio+modbus] 辨識失敗 → R2 R3 R4 = {r2} {r3} {r4} (M000={_code_of(FAIL_CODE)}),"
              f" R1 不拉高, 保持 {FAIL_HOLD_SEC} 秒")
        _out(self, 0, r2, r3, r4)
        time.sleep(FAIL_HOLD_SEC)
        _a_all_off(self)

    threading.Thread(target=run, daemon=True).start()


def _a_cleanup(self):
    """程式結束前: 兩邊都清掉、關 Modbus 連線、釋放 GPIO。"""
    _a_all_off(self)
    _mb.close()
    _gpio_cleanup(self)


pi_gpio_controller.PiGPIOController.__init__ = _a_init
pi_gpio_controller.PiGPIOController.ready = _a_ready
pi_gpio_controller.PiGPIOController.send = _a_send
pi_gpio_controller.PiGPIOController.send_fail = _a_send_fail
pi_gpio_controller.PiGPIOController.all_off = _a_all_off
pi_gpio_controller.PiGPIOController.cleanup = _a_cleanup

# ==============================================================================
# 單獨測試模式
# ==============================================================================
def _read_p(index):
    """讀回一個位置變數的全部欄位, 並換算成 mm / 度; 賽前拿來和 pendant 顯示值對照 (確認單位與座標系)。"""
    arm = _Yaskawa(HOST, PORT)
    try:
        rec = arm.read_position(index)
    finally:
        arm.close()
    dt = rec["data_type"]
    print(f"\nP{index:03d} 的內容 (High Speed Ethernet Server 原始值):")
    print(f"  data_type     = {dt}  ({POS_DATA_TYPE_NAMES.get(dt, '未知')})")
    print(f"  form (姿態)   = {rec['form']}      tool_no = {rec['tool_no']}      user_coor_no = {rec['user_coor_no']}      extended_form = {rec['extended_form']}")
    print(f"  pos (7 個整數) = {rec['pos']}")
    if dt == 0:
        print("\n  這是脈衝型位置變數, 本程式不能用。請在 pendant 把它改教成直角座標 (Base / Robot / User) 的點。")
        return
    px = rec["pos"]
    print(f"\n  換算 (X Y Z ÷ {POS_UNIT_MM}, Rx Ry Rz ÷ {POS_UNIT_DEG}):")
    print(f"  X = {px[0] / POS_UNIT_MM:.3f} mm   Y = {px[1] / POS_UNIT_MM:.3f} mm   Z = {px[2] / POS_UNIT_MM:.3f} mm")
    print(f"  Rx = {px[3] / POS_UNIT_DEG:.4f}°   Ry = {px[4] / POS_UNIT_DEG:.4f}°   Rz = {px[5] / POS_UNIT_DEG:.4f}°")
    print("\n  和 pendant 上同一個 P 的顯示值比對: 數字一樣 → 單位正確; 差 1000 倍 → 改 POS_UNIT_MM / POS_UNIT_DEG。")
    print(f"  比賽時程式會沿用這筆的 data_type / form / tool / user_coor, 只換 X Y Z; 這個點的 Z = {px[2] / POS_UNIT_MM:.3f} 可作為 Z_PICK 的參考。")


def _manual():
    """不開相機, 由鍵盤提供座標; 每次 job 把 B001 設成 1 就會拿到目前這一組。"""
    box = {"reply": REPLY_NONE}
    link = ArmLink()
    link.open()

    def pump():
        while not link._stop.is_set():
            for cmd in link.poll():
                if cmd == CMD_GET:
                    link.send(box["reply"])
            link._stop.wait(0.05)

    threading.Thread(target=pump, daemon=True).start()
    print("=" * 60)
    print(f"安川手動座標測試 (目標 {HOST}:{PORT} UDP)")
    print("  輸入 X,Y   例: 300,50        none = 之後回「沒座標」(B003=1)        q = 離開")
    print("=" * 60)
    try:
        while True:
            text = input("座標> ").strip()
            if not text:
                continue
            if text.lower() in ("q", "quit", "exit"):
                break
            if text.lower() == "none":
                box["reply"] = REPLY_NONE
                print("  已設定: 之後回 沒座標")
                continue
            try:
                x, y = (float(t) for t in text.replace(",", " ").split()[:2])
            except ValueError:
                print("  要 X,Y 兩個數字")
                continue
            box["reply"] = reply_target(x, y)
            print(f"  已設定: X={x} Y={y}")
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        link.close()
        print("\n結束")


# ==============================================================================
# 以下是安川 High Speed Ethernet Server 的通訊底層 —— 不用改
# (封包格式由 fs100.py 處理: UDP 埠 10040, 讀寫變數用 0x7a=B 變數、0x7f=位置變數)
# ==============================================================================
import fs100

_FS = fs100.FS100


class ArmError(RuntimeError):
    """控制器回了錯誤, 或連不上。code = 控制器的附加狀態碼 (沒有就是 None)。"""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class _Yaskawa:
    """一條 UDP 連線 (High Speed Ethernet Server)。上層只管呼叫 read_byte / write_byte / write_position / read_position。
    任何模式 (TEACH / PLAY / REMOTE) 都能讀寫變數, 不需要 command remote。"""

    def __init__(self, host, port):
        self.host, self.port = host, port
        self._fs = None

    def _dev(self):
        if self._fs is None:
            self._fs = _FS(self.host, timeout=HSES_TIMEOUT)
            self._fs.connect(self.port)
        return self._fs

    def close(self):
        if self._fs is not None:
            try:
                self._fs.disconnect()
            except OSError:
                pass
        self._fs = None

    def _check(self, status, what):
        """fs100 回傳 status != 0 就關連線並拋 ArmError (連不上 / 逾時 / 控制器拒絕都走這裡)。"""
        if status == _FS.ERROR_SUCCESS:
            return
        code = self._fs.errno if self._fs is not None else None
        self.close()
        if status == _FS.ERROR_CONNECTION:
            raise ArmError(f"安川 {self.host}:{self.port} 沒回應 (逾時/連不上): 檢查 IP、網路線、High Speed Ethernet Server 是否開啟", code)
        raise ArmError(f"{what} 失敗: 控制器回 status={status:#x}, 附加碼={code:#x} (查 High Speed Ethernet Server 手冊的錯誤碼表)", code)

    def read_byte(self, index):
        """讀 B<index>。"""
        var = _FS.Variable(_FS.VarType.BYTE, index)
        self._check(self._dev().read_variable(var), f"讀 B{index:03d}")
        return int(var.val)

    def write_byte(self, index, value):
        """寫 B<index> = value。"""
        var = _FS.Variable(_FS.VarType.BYTE, index, int(value))
        self._check(self._dev().write_variable(var), f"寫 B{index:03d}")

    def read_position(self, index):
        """讀 P<index>, 回傳 dict: data_type / form / tool_no / user_coor_no / extended_form / pos (7 個整數)。"""
        var = _FS.Variable(_FS.VarType.ROBOT_POSITION, index)
        self._check(self._dev().read_variable(var), f"讀 P{index:03d}")
        return dict(var.val)

    def write_position(self, index, x, y, z, template=None):
        """寫 P<index> 為直角座標 (x, y, z 單位 mm)。
        座標系 / 姿態 / Tool / User frame 沿用 template (沒給就先讀 P<index> 現值), 只換 X Y Z;
        所以該 P 賽前要先教成直角座標點 (data_type 不可為 0 脈衝型)。回傳實際寫入的 dict, 可給下一次當 template。"""
        rec = dict(template) if template is not None else self.read_position(index)
        if rec["data_type"] == 0:
            raise ArmError(f"P{index:03d} 是脈衝型位置變數, 請先在 pendant 把 P{PICK_P:03d} 教成直角座標的夾取姿態點")
        pos = list(rec["pos"])
        pos[0], pos[1], pos[2] = int(round(x * POS_UNIT_MM)), int(round(y * POS_UNIT_MM)), int(round(z * POS_UNIT_MM))
        rec["pos"] = tuple(pos)
        var = _FS.Variable(_FS.VarType.ROBOT_POSITION, index, rec)
        self._check(self._dev().write_variable(var), f"寫 P{index:03d}")
        return rec


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="安川手臂通訊: 單獨測試")
    ap.add_argument("--host", default=HOST, help="安川控制器 IP")
    ap.add_argument("--port", type=int, default=PORT, help="High Speed Ethernet Server 的 UDP 埠 (預設 10040)")
    ap.add_argument("--read-p", type=int, metavar="N", help="讀回 P<N> 全部欄位並換算 (賽前和 pendant 對照)")
    _a = ap.parse_args()
    HOST, PORT = _a.host, _a.port
    if _a.read_p is not None:
        _read_p(_a.read_p)
    else:
        _manual()
