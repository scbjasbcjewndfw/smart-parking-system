"""
车牌识别：YOLO 检测 + PaddleOCR 文字提取
流程：原图 -> YOLO 检测车牌框 -> 切出车牌 -> PaddleOCR 识别 -> 画框+标注文字 -> 保存
"""
import os
import sys
import argparse
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO
from paddleocr import PaddleOCR

# YOLO 训练好的权重（plate_exp/train_v1/weights/best.pt）
DEFAULT_YOLO_MODEL = r".\plate_exp\train_v1\weights\best.pt"
# 输出目录
DEFAULT_OUTPUT_DIR = r".\runs\ocr"

# 全局 OCR 实例（避免重复加载，提高批量处理速度）
_ocr_instance = None

def get_ocr():
    """单例获取 PaddleOCR 实例。中文车牌用 ch 模型 + 角度分类。"""
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = PaddleOCR(
            use_angle_cls=True,
            lang="ch",
            show_log=False,
        )
    return _ocr_instance


def recognize_plate(plate_img):
    """
    对切出的车牌图做 OCR。
    返回 (text, score)，识别失败返回 ("", 0.0)。
    """
    if plate_img is None or plate_img.size == 0:
        return "", 0.0

    ocr = get_ocr()
    # PaddleOCR 接收 numpy 数组（BGR）；cls=True 开启方向分类，倾斜车牌更稳
    result = ocr.ocr(plate_img, cls=True)
    if not result or not result[0]:
        return "", 0.0

    # result[0] 是 list，每个元素 [box, (text, score)]
    # 一张车牌通常只识别出一行，但保险起见取置信度最高的一条
    best_text = ""
    best_score = 0.0
    for line in result[0]:
        text, score = line[1]
        if score > best_score:
            best_text, best_score = text, score
    return best_text, best_score


def clean_plate_text(text):
    """去掉 OCR 结果中常见的车牌中间分隔符（·、•、' '、-），方便后续比对/计费。"""
    if not text:
        return ""
    for ch in ["·", "•", " ", "-", ":", "：", "．", "."]:
        text = text.replace(ch, "")
    return text.strip()


def process_image(yolo_model, img_path, output_dir):
    """对单张图片跑完整流程，返回 [{box, text, score}, ...]。"""
    img = cv2.imread(str(img_path))
    if img is None:
        print(f"[WARN] 读取失败：{img_path}")
        return []

    # 1) YOLO 检测车牌
    results = yolo_model(img, verbose=False)
    plates = []
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            conf = float(box.conf[0])
            plate_crop = img[y1:y2, x1:x2].copy()

            # 2) OCR 识别
            text, score = recognize_plate(plate_crop)
            plate_text = clean_plate_text(text)
            plates.append({
                "box": (x1, y1, x2, y2),
                "yolo_conf": conf,
                "text": plate_text,
                "ocr_score": score,
            })

    # 3) 在原图上画框 + 标注识别结果
    vis = img.copy()
    for p in plates:
        x1, y1, x2, y2 = p["box"]
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"{p['text']} ({p['ocr_score']:.2f})"
        # 文字背景，避免直接画在车牌上挡内容
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        cv2.rectangle(vis, (x1, max(0, y1 - th - 6)), (x1 + tw, y1), (0, 255, 0), -1)
        cv2.putText(vis, label, (x1, max(th, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA)

    # 4) 保存可视化结果
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(output_dir) / f"{Path(img_path).stem}_ocr.jpg"
        cv2.imwrite(str(out_path), vis)

    # 打印结果
    print(f"\n[ {Path(img_path).name} ] 检测到 {len(plates)} 个车牌：")
    for i, p in enumerate(plates, 1):
        print(f"  #{i} {p['text']}  (OCR={p['ocr_score']:.3f}, YOLO={p['yolo_conf']:.3f})")

    return plates


def main():
    parser = argparse.ArgumentParser(description="YOLO+PaddleOCR 车牌识别")
    parser.add_argument("input", nargs="?", default=r".\test.jpg",
                        help="单张图片或图片目录（默认 test.jpg）")
    parser.add_argument("--model", default=DEFAULT_YOLO_MODEL, help="YOLO 权重路径")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_DIR, help="可视化结果输出目录")
    args = parser.parse_args()

    if not Path(args.model).exists():
        print(f"[ERROR] YOLO 权重不存在：{args.model}")
        sys.exit(1)

    print(f"加载 YOLO 模型：{args.model}")
    yolo_model = YOLO(args.model)

    in_path = Path(args.input)
    if in_path.is_dir():
        exts = {".jpg", ".jpeg", ".png", ".bmp"}
        img_list = [p for p in sorted(in_path.iterdir()) if p.suffix.lower() in exts]
    else:
        img_list = [in_path]

    if not img_list:
        print(f"[ERROR] 没有找到图片：{args.input}")
        sys.exit(1)

    print(f"共 {len(img_list)} 张图片，开始处理...")
    all_results = {}
    for img_path in img_list:
        plates = process_image(yolo_model, img_path, args.output)
        all_results[img_path.name] = plates

    # 汇总
    print("\n========== 识别汇总 ==========")
    for name, plates in all_results.items():
        for p in plates:
            print(f"{name}\t{p['text']}\t{p['ocr_score']:.3f}")

    print(f"\n可视化结果已保存到：{args.output}")


if __name__ == "__main__":
    main()
