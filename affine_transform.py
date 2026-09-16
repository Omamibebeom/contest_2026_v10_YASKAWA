"""
affine_transform.py —— 像素 (cx,cy) → 手臂 (X,Y) 的仿射轉換 (純數學)

流程:
  1) affine_sample_tool.py 取樣 → 把印出的點位手寫進下面 PIXELS / ARMS。
  2) python3 affine_transform.py 驗算 (印出六個參數即成功)。
  3) 主程式: from affine_transform import pixel_to_arm
             x, y = pixel_to_arm(cx, cy)

注意: (cx,cy) 一律是整張畫面的像素; 相機一旦被移動, 點位必須重新取樣。
      ( 點位少於 3 點 / 兩清單長度不同) 時, 載入本模組就會以 numpy 的錯誤中止。
"""
import numpy as np


# ============ 學生作答區: 手寫取樣點位 (兩清單同序號 = 同一個物理點) ============
PIXELS = [
    # (cx,    cy)   相機像素, affine_sample_tool.py 印出
    (100.0, 100.0),
    (500.0, 100.0),
    (500.0, 400.0),
    (100.0, 400.0),
    (300.0, 250.0),
]

ARMS = [
    # (X,     Y)   手臂座標 mm, 從手臂教導器 (顯示板) 讀
    (600.0, -150.0),
    (600.0,  150.0),
    (375.0,  150.0),
    (375.0, -150.0),
    (487.5,    0.0),
]
#========================

def fit(pixels, arms):
    """最小平方解 T₁ = (AᵀA)⁻¹·AᵀX (X 組), T₂ 同法 (Y 組); 回傳 (2, 3) 參數矩陣。

    矩陣相乘一律用 @ (勿用 *, 那是逐格相乘)。
    """
    A = []                                   # 像素堆成 A: 每列 [cx, cy, 1]
    for k in range(len(pixels)):
        A.append([pixels[k][0], pixels[k][1], 1.0])   # 第三欄補 1 = 平移項
    arm_x, arm_y = [], []                             # 手臂座標拆成 X、Y 兩條向量
    for k in range(len(arms)):
        arm_x.append(arms[k][0])
        arm_y.append(arms[k][1])
    A = np.array(A, dtype=float)             # (m, 3)

    arm_x = np.array(arm_x, dtype=float)     # (m,)
    arm_y = np.array(arm_y, dtype=float)

# ============ 學生作答區: 座標轉換程式碼（比賽會挖空，需手寫） ============
    At = A.transpose()                                                 # Aᵀ
    AtA_inv = np.linalg.inv(At @ A)                                    # (AᵀA)⁻¹; X、Y 共用同一個反矩陣
    T11, T12, T13 = AtA_inv @ (At @ arm_x)                             # [T11,T12,T13]: 先算 AᵀX 再左乘反矩陣, 順序不可換
    T21, T22, T23 = AtA_inv @ (At @ arm_y)                             # [T21,T22,T23]
    return np.array([[T11, T12, T13], [T21, T22, T23]], dtype=float)   
#========================

PARAMS = fit(PIXELS, ARMS)      # 載入模組時用頂端手寫的點位算一次


def pixel_to_arm(cx, cy):
    """套用轉換: 像素 → 手臂座標 (X, Y)。"""
    X = PARAMS[0, 0] * cx + PARAMS[0, 1] * cy + PARAMS[0, 2]
    Y = PARAMS[1, 0] * cx + PARAMS[1, 1] * cy + PARAMS[1, 2]
    return float(X), float(Y)


if __name__ == "__main__":      # 驗算手寫點位: 能印出六個參數 = 點位格式正確且不共線
    print("X = {:.5f}*cx + {:.5f}*cy + {:.3f}".format(*PARAMS[0]))
    print("Y = {:.5f}*cx + {:.5f}*cy + {:.3f}".format(*PARAMS[1]))
