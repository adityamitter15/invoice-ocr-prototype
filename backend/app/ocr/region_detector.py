"""Locate header, table and row boundaries on the AGW receipt template."""

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Tuple

import cv2
import numpy as np


# Template constants tuned to the AGW invoice layout. All fractions are of
# image width or height on an already-normalised portrait scan.
@dataclass(frozen=True)
class TemplateConstants:
    expected_table_rows: int = 29
    min_horizontal_span_pct: float = 0.10

    header_end_band_top_pct: float = 0.05
    header_end_band_bottom_pct: float = 0.50

    row_pitch_min: int = 40
    row_pitch_max: int = 120

    # Column boundaries as fractions of image width.
    col_row_num_end: float = 0.04
    col_quantity_end: float = 0.14
    col_description_end: float = 0.75
    col_unit_price_end: float = 0.88

    fallback_header_end_pct: float = 0.28
    fallback_table_start_pct: float = 0.30
    fallback_table_end_pct: float = 0.88


TEMPLATE = TemplateConstants()
EXPECTED_TABLE_ROWS = TEMPLATE.expected_table_rows


def _find_horizontal_lines(
    cv_img: np.ndarray,
    min_span_pct: float = TEMPLATE.min_horizontal_span_pct,
) -> List[Tuple[int, int]]:
    """Return [(y_centre, line_width)] for each detected horizontal rule, top-to-bottom."""
    h, w = cv_img.shape[:2]
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    kernel_w = max(int(w * min_span_pct), 20)
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_w, 1))
    horiz = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horiz_kernel, iterations=2)

    contours, _ = cv2.findContours(horiz, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    lines: List[Tuple[int, int]] = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        if cw >= w * min_span_pct:
            lines.append((y + ch // 2, cw))

    lines.sort(key=lambda t: t[0])
    return lines


def _cluster(ys: List[int], gap: int = 10) -> List[int]:
    """Merge y-values within `gap` px of each other (average of cluster)."""
    if not ys:
        return []
    clustered: List[int] = [ys[0]]
    for y in ys[1:]:
        if abs(y - clustered[-1]) <= gap:
            clustered[-1] = (clustered[-1] + y) // 2
        else:
            clustered.append(y)
    return clustered


def _estimate_pitch(detected: List[int]) -> int:
    # Use the mode over plausible gaps rather than the median: footer box
    # edges produce sub-row-height gaps that bias the median downwards.
    gaps = [detected[i + 1] - detected[i] for i in range(len(detected) - 1)]
    plausible = [g for g in gaps if TEMPLATE.row_pitch_min <= g <= TEMPLATE.row_pitch_max]
    if plausible:
        counter = Counter(plausible)
        top = counter.most_common()
        best_count = top[0][1]
        tied = [g for g, c in top if c == best_count]
        return int(np.median(tied))
    if gaps:
        return int(np.median(gaps))
    return 0


def _fill_rows(detected: List[int], table_start: int, table_end: int) -> List[int]:
    """Project a full row-separator grid from the detected (noisy) subset.

    Returns EXPECTED_TABLE_ROWS + 1 entries so each data row is a consecutive
    pair. Falls back to an even distribution when detection fails entirely.
    """
    if not detected:
        pitch = max(1, (table_end - table_start) // (EXPECTED_TABLE_ROWS + 1))
        return [table_start + i * pitch for i in range(EXPECTED_TABLE_ROWS + 1)]

    pitch = _estimate_pitch(detected)
    if pitch < 4:
        pitch = max(1, (table_end - table_start) // (EXPECTED_TABLE_ROWS + 1))
        return [table_start + i * pitch for i in range(EXPECTED_TABLE_ROWS + 1)]

    # Anchor on the detected line with the most pitch-consistent neighbours.
    tol = max(3, int(pitch * 0.15))

    def neighbour_score(y: int) -> int:
        score = 0
        for other in detected:
            if other == y:
                continue
            delta = abs(other - y)
            multiple = round(delta / pitch)
            if multiple > 0 and abs(delta - multiple * pitch) <= tol:
                score += 1
        return score

    anchor = max(detected, key=neighbour_score)

    grid: List[int] = []
    y = anchor
    while y > table_start - pitch // 2:
        grid.append(int(y))
        y -= pitch
    grid.reverse()
    y = anchor + pitch
    while y <= table_end + pitch // 2:
        grid.append(int(y))
        y += pitch

    detected_sorted = sorted(detected)
    snapped: List[int] = []
    for gy in grid:
        near = [d for d in detected_sorted if abs(d - gy) <= tol]
        if near:
            snapped.append(int(min(near, key=lambda d: abs(d - gy))))
        else:
            snapped.append(int(gy))

    while snapped and snapped[0] < table_start - tol:
        snapped.pop(0)
    while len(snapped) > EXPECTED_TABLE_ROWS + 1:
        snapped.pop()
    while len(snapped) < EXPECTED_TABLE_ROWS + 1:
        snapped.append(snapped[-1] + pitch if snapped else table_start)
    return snapped


def detect_regions(cv_img: np.ndarray) -> Dict:
    """Return y-bounds: header_end_y, table_start_y, table_end_y, row_ys."""
    h, w = cv_img.shape[:2]

    lines = _find_horizontal_lines(cv_img, min_span_pct=TEMPLATE.min_horizontal_span_pct)

    if len(lines) < 3:
        table_start = int(h * TEMPLATE.fallback_table_start_pct)
        table_end = int(h * TEMPLATE.fallback_table_end_pct)
        row_count = EXPECTED_TABLE_ROWS
        row_ys = [table_start + int(i * (table_end - table_start) / row_count)
                  for i in range(row_count)]
        return {
            "header_end_y": int(h * TEMPLATE.fallback_header_end_pct),
            "table_start_y": table_start,
            "table_end_y": table_end,
            "row_ys": row_ys,
        }

    # Column-header separator is the widest line below the outer border.
    top_band = [
        (y, cw) for y, cw in lines
        if h * TEMPLATE.header_end_band_top_pct < y < h * TEMPLATE.header_end_band_bottom_pct
    ]
    if top_band:
        table_start_y = max(top_band, key=lambda t: t[1])[0]
    else:
        table_start_y = next((y for y, _ in lines if y > h * TEMPLATE.header_end_band_top_pct), lines[0][0])

    header_end_y = max(0, table_start_y - 5)

    # Project the table bottom from the estimated pitch - the last wide rule
    # is often the form border, not a row separator, so anchoring on pitch
    # gives a more reliable end-of-table than chasing bottom lines.
    raw_row_candidates = sorted(y for y, _ in lines if table_start_y + 8 < y < h - 20)
    row_line_ys = _cluster(raw_row_candidates)
    pitch_estimate = _estimate_pitch(row_line_ys) if row_line_ys else 0
    if pitch_estimate >= TEMPLATE.row_pitch_min:
        projected_table_end = table_start_y + (EXPECTED_TABLE_ROWS + 1) * pitch_estimate
        table_end_y = min(projected_table_end, h - 1)
    else:
        bottom_wide = [(y, cw) for y, cw in lines if y > h * 0.50 and cw >= w * 0.40]
        table_end_y = bottom_wide[-1][0] if bottom_wide else lines[-1][0]

    row_line_ys = _cluster(
        sorted(y for y, _ in lines if table_start_y < y < table_end_y + 20)
    )
    row_ys = _fill_rows(row_line_ys, table_start_y, table_end_y)

    return {
        "header_end_y": header_end_y,
        "table_start_y": table_start_y,
        "table_end_y": table_end_y,
        "row_ys": row_ys,
    }


def get_column_bounds(img_width: int) -> Dict[str, Tuple[int, int]]:
    """Hard-coded AGW column x-bounds: row_num, quantity, description, unit_price, amount."""
    w = img_width
    return {
        "row_num":     (0,                                     int(w * TEMPLATE.col_row_num_end)),
        "quantity":    (int(w * TEMPLATE.col_row_num_end),     int(w * TEMPLATE.col_quantity_end)),
        "description": (int(w * TEMPLATE.col_quantity_end),    int(w * TEMPLATE.col_description_end)),
        "unit_price":  (int(w * TEMPLATE.col_description_end), int(w * TEMPLATE.col_unit_price_end)),
        "amount":      (int(w * TEMPLATE.col_unit_price_end),  w),
    }
