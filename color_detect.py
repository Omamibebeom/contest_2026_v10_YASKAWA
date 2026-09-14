"""
color_detect.py —— 顏色偵測 (放置板、隨機板兩通道共用, 沒有視窗)

給一張畫面和一組 HSV 門檻, 找出每個色塊的中心像素 (cx, cy) 和面積。
顏色設定存在 vision_profiles.json, 一個顏色一組, 用 vision_tuner.py 產生。
"""
import json
from dataclasses import dataclass, asdict
import cv2
import numpy as np


@dataclass
class DetectConfig:
    """一個顏色的偵測參數。"""
    h_min: int = 0      # H 色相 0..179, S 飽和度 / V 亮度 0..255
    h_max: int = 179
    s_min: int = 80     # 飽和度下限拉高 → 濾掉灰白與反光
    s_max: int = 255
    v_min: int = 60     # 亮度下限 → 濾掉陰影
    v_max: int = 255
    blur: int = 3       # 模糊核大小 (0 = 不做)
    open_k: int = 3     # 開運算: 去小白點
    close_k: int = 5    # 閉運算: 補小破洞
    min_area: int = 800 # 面積小於這個當雜訊
    name: str = ""      # 顏色名 (小寫, 例 red)


def _odd(k):
    """核大小要是奇數 (OpenCV 規定)。"""
    k = max(1, int(k))
    return k if k % 2 == 1 else k + 1


def build_mask(frame, cfg):
    """畫面 → 黑白遮罩 (白 = 符合這個顏色)。"""
    img = frame
    if cfg.blur > 0:
        k = _odd(cfg.blur)
        img = cv2.GaussianBlur(img, (k, k), 0)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    lo = np.array([cfg.h_min, cfg.s_min, cfg.v_min], np.uint8)
    hi = np.array([cfg.h_max, cfg.s_max, cfg.v_max], np.uint8)
    if cfg.h_min <= cfg.h_max:
        mask = cv2.inRange(hsv, lo, hi)
    else:   # 色相是一個環, h_min > h_max 代表跨過 0/179 接縫 (紅色), 兩段合起來
        lo2 = np.array([0, cfg.s_min, cfg.v_min], np.uint8)
        hi2 = np.array([179, cfg.s_max, cfg.v_max], np.uint8)
        mask = cv2.inRange(hsv, lo2, hi) | cv2.inRange(hsv, lo, hi2)

    if cfg.open_k > 0:
        k = _odd(cfg.open_k)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    if cfg.close_k > 0:
        k = _odd(cfg.close_k)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    return mask


def detect_objects(frame, cfg):
    """找出這個顏色的所有色塊, 面積大的排前面。每件: cx, cy, area, contour。"""
    if frame is None:
        return [], np.zeros((1, 1), np.uint8)
    mask = build_mask(frame, cfg)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    objects = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < cfg.min_area:
            continue
        M = cv2.moments(cnt)                    # 用重心當中心點
        if M["m00"] == 0:
            continue
        objects.append({"cx": M["m10"] / M["m00"], "cy": M["m01"] / M["m00"],
                        "area": float(area), "contour": cnt})
    objects.sort(key=lambda o: o["area"], reverse=True)
    return objects, mask


def load_profiles(path):
    """讀 vision_profiles.json → DetectConfig 清單。"""
    with open(path, "r", encoding="utf-8") as f:
        items = json.load(f)["profiles"]
    return [DetectConfig(**d) for d in items]


def save_profiles(profiles, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"profiles": [asdict(p) for p in profiles]}, f, ensure_ascii=False, indent=2)


def detect_with_profiles(frame, profiles, dedup_px=20):
    """每個顏色各偵測一次並標上 name, 全部合起來依面積排序。

    兩個中心距離小於 dedup_px 視為同一件 (兩個顏色範圍重疊時會重複抓到), 只留面積大的。
    回傳 (objects, masks); masks 是 name → 遮罩, 給畫面顯示用。
    """
    tagged, masks = [], {}
    for p in profiles:
        objs, mask = detect_objects(frame, p)
        masks[p.name] = mask
        for o in objs:
            o["name"] = p.name
            tagged.append(o)
    tagged.sort(key=lambda o: o["area"], reverse=True)
    kept = []
    for o in tagged:
        near = any((o["cx"] - k["cx"]) ** 2 + (o["cy"] - k["cy"]) ** 2 < dedup_px ** 2 for k in kept)
        if not near:
            kept.append(o)
    return kept, masks


def biggest_color(frame, profiles, names):
    """只看 names 這幾個顏色, 回傳面積最大那件的顏色名; 都沒看到回 None。(a 通道: 舉到鏡頭前的放置板物件)"""
    objs, _ = detect_with_profiles(frame, [p for p in profiles if p.name in names])
    if not objs:
        return None
    return objs[0]["name"]
