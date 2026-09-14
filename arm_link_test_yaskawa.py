"""
arm_link_test_yaskawa.py —— 只測「樹莓派 ↔ 安川 YRC1000」的通訊 (廠商測機用)

跟比賽主程式的差別
  不開相機、不讀 vision_profiles.json、不碰 GPIO、不做座標轉換。
  只留下 arm_link.py (和比賽用的是同一支), 所以這裡測通的連線、變數編號、
  寫入順序, 比賽時完全一樣。

兩種用法
  python3 arm_link_test_yaskawa.py --selftest   job 還沒寫好時先用: 不需要 job,
                                                直接讀寫變數, 確認網路與控制器設定都對
  python3 arm_link_test_yaskawa.py              正常測試: 等 job 把 B001 設成 1,
                                                就依序給 FAKE_TARGETS 裡的假座標
  再加 --host 192.168.0.1                       臨時指定控制器 IP (不改 arm_link.py)

跑之前控制器要先設定好 (詳見 docs/yaskawa_job_interface.txt 第一節)
  1. ETHERNET SERVER 功能開啟
  2. CMD REMOTE SEL 啟用, 且 pendant 的 mode key 轉到 REMOTE
  兩項少做一項, 終端會印「錯誤碼 2100」。

注意: 寫進 P001 / P002 的是真的座標, job 會真的把手臂移過去。
      FAKE_TARGETS 請填這台手臂上安全、確定到得了的點。
"""
import time
import argparse

import arm_link

# ======= 測試用假座標 (單位 mm, 手臂座標系) =======
# 每次 job 要座標就給下一個, 用完自動從頭再來。
# 想測 job 的「B003 = 1 跳過這件」分支: 把整個清單清空成 []。
FAKE_TARGETS = [
    (300.0, 0.0),
    (300.0, 60.0),
    (300.0, -60.0),
]
# ================================================


def selftest():
    """不用 job: 直接讀一個變數、寫兩個變數, 確認通訊管道是通的。"""
    print(f"[自我測試] 目標 {arm_link.HOST}:{arm_link.PORT}")
    arm = arm_link._Yaskawa(arm_link.HOST, arm_link.PORT)
    try:
        # 1. 讀 B001: 連線、Ethernet Server、command remote 三件事一次驗完
        value = arm.read_byte(arm_link.FLAG_VAR)
        print(f"  [1/3] 讀 B{arm_link.FLAG_VAR:03d} = {value}   → 連線正常")

        # 2. 寫 B003: 驗證寫入權限
        arm.write_byte(arm_link.STATUS_VAR, 0)
        print(f"  [2/3] 寫 B{arm_link.STATUS_VAR:03d} = 0        → 寫入正常")

        # 3. 寫 P001: 驗證位置變數格式 (座標系 / 姿態 / Tool 有沒有填對)
        x, y = FAKE_TARGETS[0] if FAKE_TARGETS else (0.0, 0.0)
        arm.write_position(arm_link.PICK_P, x, y, arm_link.Z_PICK)
        print(f"  [3/3] 寫 P{arm_link.PICK_P:03d} = ({x}, {y}, {arm_link.Z_PICK})")
        print(f"\n  三項都過。請在 pendant 上看 P{arm_link.PICK_P:03d}, 數字應該和上面一樣。")
    except (OSError, ValueError, arm_link.ArmError) as e:
        print(f"\n  失敗: {e}")
        print("  對照 docs/yaskawa_job_interface.txt 第六節「常見問題」。")
    finally:
        arm.close()


def serve():
    """等 job 要座標, 依序給假座標 (和比賽主程式的迴圈一樣)。"""
    link = arm_link.ArmLink()
    link.open()
    print(f"[測試] 已啟動, 目標 {arm_link.HOST}:{arm_link.PORT}")
    if FAKE_TARGETS:
        print(f"[測試] 假座標共 {len(FAKE_TARGETS)} 個, 用完會從頭再來")
    else:
        print(f"[測試] 清單是空的 → 每次都回「沒座標」(B{arm_link.STATUS_VAR:03d} = 1)")
    print("[測試] 現在可以讓 job 把 B001 設成 1 了; Ctrl+C 離開\n")

    i = 0                                   # 已經給出去幾組
    try:
        while True:
            for cmd in link.poll():
                if cmd != arm_link.CMD_GET:
                    continue
                if not FAKE_TARGETS:
                    print(f"[第 {i + 1} 次] job 要座標 → 回「沒座標」")
                    link.send(arm_link.REPLY_NONE)
                else:
                    x, y = FAKE_TARGETS[i % len(FAKE_TARGETS)]
                    print(f"[第 {i + 1} 次] job 要座標 → 給 ({x}, {y})")
                    link.send(arm_link.reply_target(x, y))
                i += 1
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n[測試] 手動結束")
    finally:
        link.close()
        print(f"[測試] 已關閉, 這次共給了 {i} 組")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="安川手臂通訊測試 (不用相機、不用 IO)")
    ap.add_argument("--host", default=arm_link.HOST, help="安川控制器 IP")
    ap.add_argument("--selftest", action="store_true", help="不用 job, 直接讀寫變數確認通訊")
    args = ap.parse_args()

    arm_link.HOST = args.host               # ArmLink.open() 才會讀這個值, 所以先改有效

    if args.selftest:
        selftest()
    else:
        serve()
