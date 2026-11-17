# coding: utf-8
"""
车牌识别引擎(鲁棒版):针对背光、阴影、斜视角、低分辨率等难样本增强识别能力。

识别策略(层层兜底):
1. 检测:YOLO 两轮 —— 正常参数;若无框,降阈值+放大输入+TTA 再试
2. OCR:对每个车牌切图生成多个增强变体(放大/CLAHE/伽马校正/绿牌底色转白),
   逐个识别取最高置信度,高分提前退出
3. 兜底:YOLO 完全没检测到时,对全图直接 OCR 并按车牌正则过滤
"""
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO
from paddleocr import PaddleOCR

from utils.plate import is_valid_plate, normalize_plate, search_plate

# 因车牌检测代码在本地先写好再修改到flask项目里,plate_recognizer.py是作为基供别的代码调用方法

# YOLO 权重:本文件位于 car_back/car_project/service/,上两级是 car_back/,
# 训练好的权重在 car_back/plate_rec/plate_exp/train_v1/weights/best.pt
PROJECT_ROOT = Path(__file__).resolve().parents[2]
YOLO_MODEL_PATH = PROJECT_ROOT / "plate_rec" / "plate_exp" / "train_v1" / "weights" / "best.pt"

# 全局单例(避免每次请求都重新加载模型)
_yolo_model = None
_ocr_instance = None

# 车牌正则已统一到 utils/plate.py（原先本文件、plateService、userController 各写一套，
# 规则不一致导致"能识别但入不了场"）。本文件只负责识别，不再维护正则。


def get_yolo():                 # 加载 yolo 模型
    global _yolo_model
    if _yolo_model is None:
        if not YOLO_MODEL_PATH.exists():
            raise FileNotFoundError(f"YOLO 权重不存在:{YOLO_MODEL_PATH}")
        _yolo_model = YOLO(str(YOLO_MODEL_PATH))
    return _yolo_model


def get_ocr():                  # 加载 ocr 模型
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = PaddleOCR(
            use_angle_cls=True,
            lang="ch",
            show_log=False,
        )
    return _ocr_instance


# ------------------------- 图像增强变体 -------------------------

def _upscale_to_height(img, target_h=96):
    """小图放大到指定高度(保持宽高比),OCR 对 20~40px 高的小车牌识别率很差。"""
    h, w = img.shape[:2]
    if h >= target_h or h == 0:
        return img
    scale = target_h / h
    return cv2.resize(img, (int(w * scale), target_h), interpolation=cv2.INTER_CUBIC)


def _clahe(img):
    """LAB 空间 L 通道自适应直方图均衡,改善背光/阴影导致的低对比度。"""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)


def _gamma(img, gamma=0.6):
    """伽马校正:gamma<1 提亮(阴影/背光),gamma>1 压暗(过曝)。"""
    inv = 1.0 / gamma
    table = np.array([(i / 255.0) ** inv * 255 for i in range(256)]).astype("uint8")
    return cv2.LUT(img, table)


def _green_to_white(img):
    """新能源绿牌:绿色底转白底、字符加深,大幅提升 PaddleOCR 对绿牌的识别率。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # 绿色色域掩码(H 约 35~90)
    mask = cv2.inRange(hsv, (30, 60, 40), (95, 255, 255))
    out = img.copy()
    out[mask > 0] = (255, 255, 255)
    # 灰度拉对比后回三通道,字符更黑
    gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    gray = cv2.convertScaleAbs(gray, alpha=1.4, beta=-60)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def make_variants(crop):
    """为一个车牌切图生成多个增强变体,供 OCR 逐个尝试。"""
    variants = []
    up = _upscale_to_height(crop)
    variants.append(("原图", up))
    variants.append(("CLAHE", _clahe(up)))
    variants.append(("提亮", _gamma(up, 0.6)))
    variants.append(("压暗", _gamma(up, 1.6)))
    variants.append(("绿牌转白", _green_to_white(up)))
    return variants


# ------------------------- OCR -------------------------

def _ocr_best_of_variants(crop):
    """对切图的所有增强变体逐一 OCR,返回 (text, score),取最高分,高分提前退出。"""
    ocr = get_ocr()
    best_text, best_score = "", 0.0
    for name, variant in make_variants(crop):
        if variant is None or variant.size == 0:
            continue
        try:
            result = ocr.ocr(variant, cls=True)
        except Exception:
            continue
        if not result or not result[0]:
            continue
        for line in result[0]:
            text, score = line[1]
            text = clean_plate_text(text)
            if score > best_score:
                best_text, best_score = text, score
        # 高分且符合车牌格式,无需再试其它变体
        if best_score >= 0.95 and is_valid_plate(best_text):
            break
    return best_text, best_score


def recognize_plate(plate_img):
    """
    对切出的车牌小图做多变体 OCR(兼容旧接口)。
    返回 (text, score),识别失败返回 ("", 0.0)。
    """
    if plate_img is None or plate_img.size == 0:
        return "", 0.0
    return _ocr_best_of_variants(plate_img)


def clean_plate_text(text):
    """规范化 OCR 文本：去分隔符、全角转半角、统一大写。

    实现委托给 ``utils.plate.normalize_plate``，保证识别端与入库端同一口径。

    Args:
        text: OCR 原始文本。

    Returns:
        规范化后的车牌文本，输入为空时返回空串。
    """
    return normalize_plate(text)


# ------------------------- 检测 -------------------------

def _detect(img, conf, imgsz, augment):
    """跑一轮 YOLO 检测,返回 [(x1,y1,x2,y2,conf), ...] 按置信度降序。"""
    model = get_yolo()
    results = model(img, conf=conf, imgsz=imgsz, augment=augment, verbose=False)
    boxes = []
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            boxes.append((x1, y1, x2, y2, float(box.conf[0])))
    boxes.sort(key=lambda b: -b[4])
    return boxes


def _ocr_whole_image(img):
    """兜底:YOLO 没检测到车牌时,对全图直接 OCR,筛出符合车牌格式的文本。"""
    ocr = get_ocr()
    found = []
    up = img if max(img.shape[:2]) >= 1200 else _upscale_to_height(img, 960)
    try:
        result = ocr.ocr(up, cls=True)
    except Exception:
        return found
    if not result or not result[0]:
        return found
    h_img, w_img = img.shape[:2]
    for line in result[0]:
        (box, (text, score)) = line
        matched = search_plate(text)
        if not matched:
            continue
        # 用 OCR 文本框当车牌框,裁回原图坐标
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x1, y1 = max(int(min(xs)) - 4, 0), max(int(min(ys)) - 4, 0)
        x2, y2 = min(int(max(xs)) + 4, w_img), min(int(max(ys)) + 4, h_img)
        found.append({
            "box": (x1, y1, x2, y2),
            "yolo_conf": 0.0,
            "text": matched,
            "ocr_score": score,
            "source": "whole_ocr",
        })
    return found


def recognize_array(img):
    """
    核心入口:对一张 BGR 格式的 numpy 图片执行完整识别(带多级兜底)。

    流程:第一轮常规检测 -> 第二轮低阈值+大图+TTA -> 全图 OCR 兜底

    返回 list[dict],每个元素:
      {"box": (x1,y1,x2,y2), "yolo_conf": float, "text": str, "ocr_score": float,
       "source": "yolo" | "whole_ocr"}
    """
    if img is None:
        return []

    plates = []
    # 第一轮:常规参数
    boxes = _detect(img, conf=0.25, imgsz=960, augment=True)
    # 第二轮:仍无框则放宽阈值、放大输入再试(远小车牌/极端角度)
    if not boxes:
        boxes = _detect(img, conf=0.10, imgsz=1280, augment=True)

    for x1, y1, x2, y2, conf in boxes:
        plate_crop = img[max(y1, 0):y2, max(x1, 0):x2].copy()
        if plate_crop.size == 0:
            continue
        text, score = _ocr_best_of_variants(plate_crop)
        plates.append({
            "box": (x1, y1, x2, y2),
            "yolo_conf": conf,
            "text": text,
            "ocr_score": score,
            "source": "yolo",
        })

    # 兜底:YOLO 两轮都没框,或所有框 OCR 全失败 -> 全图 OCR
    if not any(p["text"] for p in plates):
        for p in _ocr_whole_image(img):
            plates.append(p)

    return plates


def draw_plates(img, plates):
    """在原图副本上画车牌框 + 车牌号标注,返回可视化图片(BGR numpy)。"""
    vis = img.copy()
    for p in plates:
        x1, y1, x2, y2 = p["box"]
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"{p['text']} ({p['ocr_score']:.2f})"
        # 文字背景,避免直接画在车牌上挡内容
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        cv2.rectangle(vis, (x1, max(0, y1 - th - 6)), (x1 + tw, y1), (0, 255, 0), -1)
        cv2.putText(vis, label, (x1, max(th, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA)
    return vis


def decode_image(image_bytes):
    """把上传的图片字节流解码成 OpenCV BGR 图片,失败返回 None。"""
    arr = np.frombuffer(image_bytes, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)
