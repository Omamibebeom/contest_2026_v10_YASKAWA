import socket

ROBOT_IP = "192.168.0.1"  # 請修改為實際手臂 IP
ROBOT_PORT = 80

# P001 (X=123, Y=456, 其餘補 0), 12 個欄位依安川手冊 8.3.2 LOADV 格式 2:
#   4        = 型別 (4 = 機器人軸位置變數 P)
#   1        = 變數編號 (P001)
#   1        = 位置資料型態 (0 = 脈波, 1 = 直交)
#   1        = 座標系 (0 = Base, 1 = Robot, 2~65 = User1~64, 66 = Tool)  ← 注意: 1 是 Robot, 不是 Base
#   123,456,0 = X, Y, Z (mm)
#   0,0,0    = Rx, Ry, Rz (度)
#   0        = 姿態型式 Type
#   0        = 工具號碼 Tool No.
# 這支只驗證封包能不能寫進去; 比賽用的座標系 / 姿態 / Tool 以 arm_link.py 的「賽前設定」為準。
data = "4,1,1,1,123,456,0,0,0,0,0,0"

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((ROBOT_IP, ROBOT_PORT))

    # 1. 握手連線
    s.sendall(b"CONNECT Robot_access\r\n")
    print("CONNECT 回應:", s.recv(1024).decode("ascii", errors="ignore").strip())

    # 2. 發送 LOADV 請求 (長度為字串長度 + 1 個 \r)
    s.sendall(f"HOSTCTRL_REQUEST LOADV {len(data) + 1}\r\n".encode("ascii"))
    print("LOADV 請求回應:", s.recv(1024).decode("ascii", errors="ignore").strip())

    # 3. 發送座標資料
    s.sendall((data + "\r").encode("ascii"))
    print("寫入結果:", s.recv(1024).decode("ascii", errors="ignore").strip())
