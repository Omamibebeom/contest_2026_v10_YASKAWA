"""
modbus_test_yaskawa.py —— 只測「樹莓派 ↔ 安川」的 Modbus TCP 那條路

比賽時 a 通道的顏色訊號是「繼電器 + Modbus 同時送」(見 arm_link.py 檔頭)。這支程式不開相機,
讓你在接線還沒好、或想單獨驗證 Modbus 位址對照時, 用鍵盤把訊號送出去、在安川的輸入監看畫面對答案。

三種用法
  python3 modbus_test_yaskawa.py --selftest    連線 → 讀外部輸入 → 讀外部輸出 → 寫/讀 M000, 三項各印結果
  python3 modbus_test_yaskawa.py               互動 (a 通道): 顯示 ready (外部輸出 #30030), 按鍵送訊號:
                                                 1~9 = IO_CODES 第 1~9 個顏色   f = 失敗碼   0 = 全關   q = 離開
  python3 modbus_test_yaskawa.py --coord       b 通道: 等 job 把外部輸出 #30031 設 ON, 就把假座標寫進 M010~M012
                                                 並把外部輸入 #20034 設 ON; job 把 #30031 設 OFF 後自動放下 #20034
  再加 --host 192.168.0.1                       臨時指定控制器 IP (不改 arm_link.py)

送出去的訊號【繼電器也會一起動】(和比賽一樣); 沒接繼電器板或不在樹莓派上時是模擬模式, 只印字。

位址對照 (實機已驗證; 要改就改 arm_link.py 的 MB_* 常數):
  繼電器 R1 R2 R3 R4  →  外部輸入 #20030 #20031 #20032 #20033   (coil 0~3)
  ready               ←  外部輸出 #30030                        (discrete input 0)
  M000                =  顏色數字碼 R2*4 + R3*2 + R4 (預設 red=1 blue=2 green=3, 失敗碼 7)
  b 通道: 要座標 ← 外部輸出 #30031 (discrete input 1); M010 = X×10, M011 = Y×10 (0.1 mm, 16-bit 有號), M012 = 0 有 / 1 沒;
          寫好了 → 外部輸入 #20034 (coil 4)
"""
import sys
import time
import socket
import argparse
import threading

import arm_link                                  # import 時就把 PiGPIOController 換成「GPIO + Modbus」版
from pi_gpio_controller import PiGPIOController, IO_CODES, FAIL_CODE, HOLD_SEC, FAIL_HOLD_SEC


def selftest():
    """三項各自獨立印結果, 一項失敗也繼續, 一次看完。回傳 True = 三項都過。"""
    host, port = arm_link.HOST, arm_link.MODBUS_PORT
    print(f"=== Modbus 自我檢查: {host}:{port} ===")

    print("[1/3] TCP 連線 ...", end=" ", flush=True)
    try:
        socket.create_connection((host, port), timeout=3).close()
        print("OK")
    except socket.timeout:
        print("失敗 (逾時): 控制器沒回應 → 檢查網路線、樹莓派有線 IP 是否 192.168.0.x、控制器 IP 是否 " + host)
        return False
    except ConnectionRefusedError:
        print("失敗 (拒絕連線): 控制器有回應, 但 502 埠沒開 → 確認控制器的 Modbus TCP (CPU Board) 選項已啟用")
        return False
    except OSError as e:
        print(f"失敗: {e}")
        return False

    mb = arm_link._mb
    ok = True

    print("[2/3] 讀外部輸入 (coil 0~63 ↔ #20030~) 與外部輸出 (discrete input 0~63 ↔ #30030~) ...", end=" ", flush=True)
    co = mb._call("read_coils", address=arm_link.MB_COIL_BASE, count=arm_link.MB_COIL_BITS)
    di = mb._call("read_discrete_inputs", address=arm_link.MB_DI_BASE, count=arm_link.MB_COIL_BITS)
    if co is None or di is None:
        print("失敗 → 控制器拒絕或位址不對, 檢查外部輸入/輸出的 Modbus 對照 (arm_link.py 的 MB_* 常數)")
        ok = False
    else:
        print("OK")
        print(f"      外部輸入 #20030~#20037 (R1~R4 在前四位): {[int(b) for b in co.bits[:8]]}")
        print(f"      外部輸出 #30030~#30037 (ready 在第一位):  {[int(b) for b in di.bits[:8]]}")

    print("[3/3] 寫 M000 = 123 再讀回 ...", end=" ", flush=True)
    w = mb._call("write_registers", address=arm_link.MB_REG_CODE, values=[123])
    r = mb._call("read_holding_registers", address=arm_link.MB_REG_CODE, count=1)
    if w is None or r is None or r.registers[0] != 123:
        print(f"失敗 (讀回 {None if r is None else r.registers[0]}) → 檢查 M 暫存器的 Modbus 對照 (arm_link.py 的 MB_REG_* 常數)")
        ok = False
    else:
        print("OK (讀回 123)")
        mb._call("write_registers", address=arm_link.MB_REG_CODE, values=[0])   # 清回 0

    print("=== 通過: 接下來用互動模式送訊號, 到安川的輸入監看畫面對照 ===" if ok else "=== 請先排除上面的問題 ===")
    return ok


def interactive():
    """鍵盤送訊號 + 背景顯示 ready 的變化。"""
    gpio = PiGPIOController()               # 已被 arm_link 換成 GPIO + Modbus 版
    names = list(IO_CODES)
    print(__doc__)
    print("[test] 數字鍵對應:")
    for i, n in enumerate(names, start=1):
        r2, r3, r4 = IO_CODES[n]
        print(f"      {i} = {n:8s} R2 R3 R4 = {r2} {r3} {r4}   M000 = {arm_link._code_of(IO_CODES[n])}")
    print(f"      f = 失敗碼  R2 R3 R4 = {FAIL_CODE}   M000 = {arm_link._code_of(FAIL_CODE)}")
    print(f"      (成功碼保持 {HOLD_SEC} 秒、失敗碼保持 {FAIL_HOLD_SEC} 秒; 兩次送訊號要隔開, 別連按)")

    stop = threading.Event()

    def watch_ready():
        last = None
        while not stop.is_set():
            now = gpio.ready()
            if now != last:
                print(f"\n[ready] {'ON  ← 安川請我們辨識' if now else 'OFF'}   (GPIO26 或 #30030 任一)")
                print("按鍵> ", end="", flush=True)
                last = now
            time.sleep(0.2)

    threading.Thread(target=watch_ready, daemon=True).start()
    try:
        while True:
            key = input("按鍵> ").strip().lower()
            if key in ("q", "quit", "exit"):
                break
            if key == "f":
                gpio.send_fail()
            elif key == "0":
                gpio.all_off()
                print("[test] 全關")
            elif key.isdigit() and 1 <= int(key) <= len(names):
                gpio.send(names[int(key) - 1])
            elif key:
                print("  可用: 1~9 / f / 0 / q")
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        stop.set()
        gpio.cleanup()
        print("\n[test] 結束")


# ======= b 通道測試用假座標 (單位 mm, 手臂座標系) =======
# 只驗通訊, 座標本身不需要準; 但 job 若照 M010/M011 走會真的移動, 務必填安全的點。
FAKE_TARGETS = [
    (300.0, 0.0),
    (300.0, 60.0),
    (300.0, -60.0),
]
# =====================================================


def coord_test():
    """b 通道 (Modbus): 用比賽同一支 ArmLink, #30031=ON 就回 FAKE_TARGETS 的下一點, 用完從頭再來。"""
    link = arm_link.ArmLink()
    link.open()
    print(f"[test] 等 job 把外部輸出 #30031 設 ON ... (假座標 {len(FAKE_TARGETS)} 個, Ctrl+C 離開)")
    print("[test] 收到請求後: M010 = X×10, M011 = Y×10, M012 = 0, 外部輸入 #20034 = ON; job 讀完把 #30031 設 OFF 就會放下 #20034\n")
    i = 0
    try:
        while True:
            for cmd in link.poll():
                if cmd != arm_link.CMD_GET:
                    continue                    # (Ethernet Server 的 B001 請求若同時來, 也會照 ArmLink 的來源回給它)
                x, y = FAKE_TARGETS[i % len(FAKE_TARGETS)]
                i += 1
                print(f"[test] 第 {i} 次請求 → 寫 X={x} Y={y} (M010={int(x * arm_link.COORD_SCALE)}, M011={int(y * arm_link.COORD_SCALE) & 0xFFFF})")
                link.send(arm_link.reply_target(x, y))
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n[test] 手動結束")
    finally:
        link.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="安川 Modbus 通訊測試 (比賽不用)")
    ap.add_argument("--host", default=arm_link.HOST, help="安川控制器 IP")
    ap.add_argument("--port", type=int, default=arm_link.MODBUS_PORT, help="Modbus 埠 (預設 502)")
    ap.add_argument("--selftest", action="store_true", help="只做三項自我檢查")
    ap.add_argument("--coord", action="store_true", help="b 通道: 等 #30031 回假座標")
    args = ap.parse_args()
    arm_link.HOST, arm_link.MODBUS_PORT = args.host, args.port
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    if args.coord:
        coord_test()
        sys.exit(0)
    interactive()
