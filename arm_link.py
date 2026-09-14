"""
arm_link.py —— 樹莓派 ↔ 安川 YRC1000 手臂通訊 (b 通道: 把座標送給手臂)

怎麼運作
  手臂 job 把 B001 設成 1 (= 我要座標)
  → 本程式把下一件的座標寫進 P001 (夾取點) 與 P002 (夾取點正上方)
  → 寫 B003: 0 = 有座標, 1 = 沒座標 (該顏色已給完或 PICK_ORDER 用完, 這件跳過)
  → 最後把 B001 設回 0 (= 寫好了)
  → job 看到 B001 變 0, 先判 B003, 再讀 P002 / P001 去夾
  變數編號固定: B001 旗標 / B003 狀態 / P001 夾取點 / P002 正上方 (job 端要用同樣的編號)

賽前要填的 (下面「賽前設定」區, 三項都要在安川實機上量, 不能沿用別台手臂的數字)
  1. HOST                         安川控制器的 IP
  2. COORD_FRAME / RX RY RZ / POSE_TYPE / TOOL_NO
                                  先在 pendant 把手臂 Jog 到「夾取姿態、剛好碰到物件」的點教成 P010,
                                  再跑  python3 arm_link.py --read-p 10  照終端提示抄
                                  (affine 取樣時 pendant 顯示的是哪個座標系, COORD_FRAME 就填哪一個)
  3. Z_PICK / Z_SAFE              夾取高度 / 安全通過高度, 量出來填

安川控制器要先開 (老師賽前確認; 沒開的話終端會印錯誤碼 2100 與說明)
  - ETHERNET SERVER 功能 (維護模式 → MANAGEMENT MODE → SYSTEM → SETUP → OPTION FUNCTION → NETWORK FUNCTION SETTING)
  - command remote: {IN/OUT} → {PSEUDO INPUT SIG} 的 CMD REMOTE SEL 設為啟用, 且 pendant 的 mode key 轉到 REMOTE

單獨測試 (不開相機)
  python3 arm_link.py                 手動輸入座標; 每次 job 把 B001 設 1 就拿到目前這一組
  python3 arm_link.py --read-p 10     讀回 P010 的座標系 / 姿態 / Tool, 抄進賽前設定
  python3 arm_link.py --host 192.168.0.1   臨時指定 IP (不改檔)

主程式怎麼用 (main_contest.py 已寫好, 這裡只是說明)
  link = ArmLink(); link.open()
  每一圈:  for cmd in link.poll(): link.send(b.handle(cmd))
  結束:    link.close()
"""
import queue
import socket
import argparse
import threading

# ======================= 賽前設定 (只改這一區) =======================
HOST = "192.168.0.1"      # 安川控制器 IP
PORT = 80                   # 安川 Ethernet Server 固定用 TCP 埠 80, 不用改

COORD_FRAME = 1             # 座標系: 0=Base 1=Robot 2~65=User1~64 66=Tool (--read-p 抄)
RX, RY, RZ = 180.0, 0.0, 0.0   # 夾爪姿態 (度) (--read-p 抄)
POSE_TYPE = 0               # 姿態型式 Type (--read-p 抄)
TOOL_NO = 0                 # 工具號碼 (--read-p 抄)
Z_PICK = 20.0               # 夾取高度 (mm)
Z_SAFE = 50.0               # 安全通過高度 (mm)
WRITE_APPROACH = True       # False = 不寫 P002 (job 自己用相對移動下降時可關)
# =====================================================================

# ---------- 固定的變數編號 (job 端照這個寫; 不開放修改) ----------
FLAG_VAR = 1                # B001: job 寫 1 = 要座標; 樹莓派寫 0 = 寫好了
STATUS_VAR = 3              # B003: 0 = 有座標, 1 = 沒座標
PICK_P = 1                  # P001: 夾取點
ABOVE_P = 2                 # P002: 夾取點正上方
ST_OK, ST_NONE = 0, 1

POLL_SEC = 0.3              # 每隔幾秒問一次 B001
RETRY_SEC = 1.0             # 通訊失敗後隔幾秒再試
REPLY_WAIT_SEC = 5.0        # 等主程式算回覆最多幾秒 (正常不到 0.1 秒)

# ---------- 主程式用的指令字與回覆 ----------
CMD_GET = "GET"             # 手臂要座標 (B001 = 1 時由本程式產生)
CMD_SCAN = "SCAN"           # 以下四個本程式不會產生, 保留給主程式的 handle() 使用
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
        self.state = "INIT"             # INIT / POLL / SERVE / ERROR (畫面顯示用)
        self.note = ""                  # 最近一句訊息 (畫面顯示用)
        self.served = 0                 # 已經給出去幾件

    def open(self):
        """開始和手臂講話 (主程式在快照完成後才呼叫)。馬上回來, 連線在背景進行。"""
        self._arm = _Yaskawa(HOST, PORT)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def poll(self):
        """收這一圈的指令, 回傳清單 (可能是空的)。"""
        cmds = []
        while True:
            try:
                cmds.append(self._cmds.get_nowait())
            except queue.Empty:
                return cmds

    def send(self, reply):
        """把主程式算好的回覆交給背景執行緒寫進安川變數。"""
        self._replies.put(reply)

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
        所以 job 看到 B001 變 0 時, 其他變數一定已經是這一輪的新值。"""
        if reply.get("kind") == "target":
            self._arm.write_position(PICK_P, reply["x"], reply["y"], Z_PICK)
            if WRITE_APPROACH:
                self._arm.write_position(ABOVE_P, reply["x"], reply["y"], Z_SAFE)
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
# 單獨測試模式
# ==============================================================================
def _read_p(index):
    """讀回一個位置變數, 賽前抄「座標系 / 姿態 / Tool」用。"""
    labels = ["位置資料型態", "座標系", "X", "Y", "Z", "Rx", "Ry", "Rz", "Type(姿態)", "Tool No."]
    arm = _Yaskawa(HOST, PORT)
    try:
        fields = arm.read_position(index)
    finally:
        arm.close()
    print(f"\nP{index:03d} 的內容:")
    for label, value in zip(labels, fields):
        print(f"  {label:14s} = {value}")
    if len(fields) >= 10:
        print("\n抄進 arm_link.py 的「賽前設定」:")
        print(f"  COORD_FRAME = {fields[1]}")
        print(f"  RX, RY, RZ = {fields[5]}, {fields[6]}, {fields[7]}")
        print(f"  POSE_TYPE = {fields[8]}")
        print(f"  TOOL_NO = {fields[9]}")
        print(f"  (這個點的 Z = {fields[4]}, 可作為 Z_PICK 的參考)")


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
    print(f"安川手動座標測試 (目標 {HOST}:{PORT})")
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
# 以下是安川 Ethernet Server Function 的通訊底層 —— 不用改
# (格式依安川手冊 HW1483358 第 8 章; 章節號寫在各處註解, 方便對照)
# ==============================================================================
TIMEOUT = 5.0           # 收發逾時 (秒); 控制器 Keep-Alive 模式約 30 秒無指令會關閉連線 (8.1.4)
KEEP_ALIVE = 100        # 一條連線連下幾個指令, 用完自動重連 (8.3.1.2 允許 2~32767; 頻繁開關 socket 會耗盡, 8.1.4)

ERRORS = {              # 控制器回的錯誤碼 → 說明 (手冊表 11-1)
    1010: "指令錯誤", 1011: "指令運算元數量錯誤", 1012: "指令運算元數值超出範圍", 1013: "指令運算元長度錯誤",
    2010: "機械手臂動作中", 2060: "發生錯誤/警報", 2070: "伺服電源關閉", 2080: "模式不正確",
    2100: "未設定 command remote (CMD REMOTE SEL 要啟用, mode key 轉 REMOTE)",
    2110: "該資料無法存取", 2120: "該資料無法載入",
    4130: "位置資料不存在", 4140: "位置變數型別不正確", 5180: "資料數目不正確", 5200: "資料超出範圍",
}


class ArmError(RuntimeError):
    """控制器回了錯誤, 或回覆格式不對。code = 錯誤碼 (沒有就是 None)。"""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def _explain(text):
    """'ERROR:[LOADV] is not successful(2100).' → '2100 未設定 command remote ...'"""
    left, right = text.find("("), text.find(")")
    if left >= 0 and right > left and text[left + 1:right].strip().isdigit():
        code = int(text[left + 1:right])
        return f"錯誤碼 {code} {ERRORS.get(code, '(見手冊表 11-1)')}", code
    return text, None


class _Yaskawa:
    """一條連線, 額度用完或出錯就自動重建。上層只管呼叫 read_byte / write_byte / write_position。"""

    def __init__(self, host, port):
        self.host, self.port = host, port
        self._sock = None
        self._buf = b""
        self._left = 0

    def _open(self):
        self.close()
        self._sock = socket.create_connection((self.host, self.port), TIMEOUT)
        self._sock.settimeout(TIMEOUT)
        self._buf = b""
        self._send_line(f"CONNECT Robot_access Keep-Alive:{KEEP_ALIVE} ")    # 8.3.1.2 (n 後面有一個空白)
        self._left = KEEP_ALIVE
        res = self._read_line()
        if not res.startswith("OK"):                                        # 8.3.1.3
            self.close()
            raise ArmError(f"安川拒絕連線: {res}")

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock, self._buf, self._left = None, b"", 0

    def _send_line(self, text):
        self._sock.sendall((text + "\r\n").encode("ascii"))                  # 指令列以 <CR><LF> 結尾 (8.3.1.4)

    def _read_line(self):
        """讀一則回覆。有資料的回覆只有 <CR>, 其他是 <CR><LF> (8.3.1.7), 所以讀到 <CR> 為止,
        後面若緊接 <LF> 就一起吃掉; 剩下的位元組留給下一個指令。"""
        while b"\r" not in self._buf:
            try:
                chunk = self._sock.recv(256)
            except socket.timeout:
                raise ArmError(f"安川 {self.host}:{self.port} 沒回應 (逾時)")
            if not chunk:
                raise ArmError("安川關閉了連線")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\r", 1)
        if self._buf.startswith(b"\n"):
            self._buf = self._buf[1:]
        return line.decode("ascii", errors="ignore").strip()

    def _request(self, command, data):
        """送一個指令並回傳回覆字串。出錯就關連線再拋出 (控制器出錯時也會自己關, 8.3.1.5)。"""
        if self._sock is None or self._left <= 0:
            self._open()
        try:
            size = len(data.encode("ascii")) + 1                            # Size = 資料位元組數 + 結尾 <CR> (8.3.1.4)
            self._send_line(f"HOSTCTRL_REQUEST {command} {size}")
            self._left -= 1
            res = self._read_line()
            if not res.startswith("OK"):
                raise ArmError(f"{command} 被拒: {res}")
            self._sock.sendall((data + "\r").encode("ascii"))              # 指令資料以 <CR> 結尾 (8.3.1.6)
            answer = self._read_line()
            if answer.upper().startswith("ERROR") or answer.startswith("NG"):
                text, code = _explain(answer)
                raise ArmError(f"{command} 失敗: {text}", code)
            return answer
        except (OSError, ArmError):
            self.close()
            raise

    def read_byte(self, index):
        """讀 B<index> (SAVEV, 型別 0 = 位元組變數)。"""
        return int(self._request("SAVEV", f"0,{index}").split(",")[0])

    def write_byte(self, index, value):
        """寫 B<index> = value (LOADV 格式 1: 型別,編號,數值)。"""
        return self._request("LOADV", f"0,{index},{int(value)}")

    def write_position(self, index, x, y, z):
        """寫 P<index> 為直交座標 (LOADV 格式 2, 手冊 8.3.2), 12 個欄位依序:
        型別 4, 編號, 位置資料型態 1=直交, 座標系, X, Y, Z, Rx, Ry, Rz, Type(姿態), Tool No."""
        data = (f"4,{index},1,{COORD_FRAME},{x:.3f},{y:.3f},{z:.3f},"
                f"{RX:.4f},{RY:.4f},{RZ:.4f},{POSE_TYPE},{TOOL_NO}")
        return self._request("LOADV", data)

    def read_position(self, index):
        """讀 P<index>, 回傳欄位清單: 位置資料型態, 座標系, X, Y, Z, Rx, Ry, Rz, Type, Tool No."""
        return [f.strip() for f in self._request("SAVEV", f"4,{index}").split(",")]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="安川手臂通訊: 單獨測試")
    ap.add_argument("--host", default=HOST, help="安川控制器 IP")
    ap.add_argument("--port", type=int, default=PORT, help="埠 (預設 80)")
    ap.add_argument("--read-p", type=int, metavar="N", help="讀回 P<N> (賽前抄座標系/姿態/Tool)")
    _a = ap.parse_args()
    HOST, PORT = _a.host, _a.port
    if _a.read_p is not None:
        _read_p(_a.read_p)
    else:
        _manual()
