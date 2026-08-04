#!/usr/bin/env python3
"""
quality.py — 四层自动检查的分级/汇总工具（v3 重构新增）。

四层检查对应关系（详见 SKILL.md）：
- L1 输入数据检查：表格可读性/列存在性/图片URL有效性 —— 复用
  `parse_table_manifest.py` 现有的 issues 结构（level=error/warning）。
- L2 AI识别结果检查：bbox 合理性、空结果 —— 复用 `bbox_common.validate_bbox` /
  `bbox_common.bbox_quality_issues`。
- L3 裁剪前几何检查：bbox 与目标画布兼容性、放大倍数 —— 复用
  `geometry.validate_crop_geometry`，本模块补充放大倍数检查
  （`upscale_issue`）。
- L4 输出文件复验：文件写入/尺寸/文件大小 —— 由调用方（`crop_by_bbox.py`）
  在保存后立即重新打开校验，异常时产生 error 级 reason。

本模块不做任何文件 IO，只负责：
1. 统一的三级判定（completed / attention / failed）；
2. 三级输出目录命名（中文说明）；
3. 低分辨率放大倍数检查规则。
"""

TIER_COMPLETED = "completed"
TIER_ATTENTION = "attention"
TIER_FAILED = "failed"

# 三级输出目录（替代旧版四级 ok/needs_review/unrecognized/failed）
TIER_DIRNAMES = {
    TIER_COMPLETED: "completed-成功生成的成品",
    TIER_ATTENTION: "attention-需要检查的图片",
    TIER_FAILED: "failed-处理失败的文件",
}

# 放大倍数超过该阈值时，标记为 attention（不算错误，只是提示复核画质）。
UPSCALE_ATTENTION_THRESHOLD = 4.0


def classify_reasons(reasons):
    """
    根据 reasons 列表（每项含 severity: error/warning）判定三级 tier。
    - 含任意 error -> failed
    - 无 error 但含 warning -> attention
    - 无任何 reason -> completed
    """
    if any(r.get("severity") == "error" for r in reasons):
        return TIER_FAILED
    if reasons:
        return TIER_ATTENTION
    return TIER_COMPLETED


def upscale_issue(scale_factor, threshold=UPSCALE_ATTENTION_THRESHOLD):
    """
    检查裁剪区域放大到输出尺寸的倍数。放大本身不算异常（优先 LANCZOS 放大，
    只要放大后元素仍在目标尺寸内就计入 completed），仅当放大倍数超过阈值时
    才返回一条 warning 级提示（供人工关注画质，不影响主流程）。

    返回 reason dict 或 None。
    """
    if scale_factor is None or scale_factor <= threshold:
        return None
    return {
        "code": "high_upscale_ratio",
        "severity": "warning",
        "message": f"裁剪区域放大倍数达 {scale_factor:.2f}x（阈值 {threshold:g}x），画质可能下降，建议人工确认",
    }


def merge_reasons(*reason_lists):
    """合并多组 reasons，按 (code, message) 去重，保持首次出现顺序。"""
    seen = set()
    merged = []
    for reasons in reason_lists:
        for r in reasons:
            key = (r.get("code"), r.get("message"))
            if key not in seen:
                seen.add(key)
                merged.append(r)
    return merged


def summarize_counts(tiers):
    """给定一组 tier 字符串（每张图/每条记录一个），返回三级数量统计字典。"""
    counts = {TIER_COMPLETED: 0, TIER_ATTENTION: 0, TIER_FAILED: 0}
    for t in tiers:
        counts[t] = counts.get(t, 0) + 1
    return counts
