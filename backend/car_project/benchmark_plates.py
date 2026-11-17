# coding: utf-8
"""新旧识别管线对比基准(临时脚本,跑完可删)。"""
import random
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, r"D:\PythonCode\giteeProject\wuliu\car_back\car_project")
from service import plate_recognizer as pr  # noqa: E402

TEST_DIR = Path(r"D:\PythonCode\giteeProject\wuliu\car_back\plate_rec\dataset\images\test")
PLATE_RE = pr.PLATE_RE


def old_pipeline(img):
    """旧逻辑:单次默认检测 + 原图切图直接 OCR。"""
    model = pr.get_yolo()
    results = model(img, verbose=False)
    out = []
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            crop = img[y1:y2, x1:x2]
            text, score = "", 0.0
            ocr = pr.get_ocr()
            res = ocr.ocr(crop, cls=True)
            if res and res[0]:
                for line in res[0]:
                    t, s = line[1]
                    t = pr.clean_plate_text(t)
                    if s > score:
                        text, score = t, s
            out.append({"text": text, "ocr_score": score, "yolo_conf": float(box.conf[0])})
    return out


def evaluate(name, img, old=True):
    if old:
        plates = old_pipeline(img)
    else:
        plates = pr.recognize_array(img)
    best = max(plates, key=lambda p: p["ocr_score"]) if plates else None
    if best is None:
        return "未检出", "", 0.0
    valid = bool(PLATE_RE.search(best["text"]))
    return ("识别成功" if valid else "文本非车牌"), best["text"], best["ocr_score"]


imgs = sorted(TEST_DIR.glob("*.jpg"))
random.seed(42)
sample = random.sample(imgs, 30)
extra = [Path(r"D:\PythonCode\giteeProject\wuliu\car_back\plate_rec\test.jpg"),
         Path(r"D:\PythonCode\giteeProject\wuliu\car_back\plate_rec\test1.jpg")]

old_ok = new_ok = 0
rows = []
for p in extra + sample:
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        continue
    s_old = evaluate(p.name, img, old=True)
    s_new = evaluate(p.name, img, old=False)
    old_ok += s_old[0] == "识别成功"
    new_ok += s_new[0] == "识别成功"
    flag = "  <-- 改善" if (s_old[0] != "识别成功" and s_new[0] == "识别成功") else ""
    rows.append(f"{p.name:38s} 旧:{s_old[0]}({s_old[1]}|{s_old[2]:.2f})  新:{s_new[0]}({s_new[1]}|{s_new[2]:.2f}){flag}")

print("\n".join(rows))
print(f"\n===== 汇总:{len(rows)} 张图 =====")
print(f"旧管线 识别成功: {old_ok} ({old_ok/len(rows)*100:.0f}%)")
print(f"新管线 识别成功: {new_ok} ({new_ok/len(rows)*100:.0f}%)")
