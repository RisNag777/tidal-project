import re
from collections import defaultdict

import fitz

TIME_RE = re.compile(r"^\d{4}$")
HEIGHT_RE = re.compile(r"^-?\d+\.\d{2}$")
DAY_RE = re.compile(r"^\d{1,2}$")
TIDE_LETTER_RE = re.compile(r"^[A-Z]{1,2}$")


def _classify_tides_for_day(pairs):
    pairs = sorted(pairs, key=lambda item: item[0])
    if not pairs:
        return []

    heights = [height for _, height in pairs]
    median = sorted(heights)[len(heights) // 2]
    classified = []
    for time_str, height in pairs:
        tide_type = "high" if height >= median else "low"
        classified.append((tide_type, time_str, height))
    return classified


def _format_time(raw_time):
    return f"{raw_time[:2]}:{raw_time[2:]}"


def _update_day(day_num, side, left_day, right_day):
    if 1 <= day_num <= 15:
        if side == "left":
            return day_num, right_day
        return left_day, right_day
    if 16 <= day_num <= 31:
        return left_day, day_num
    return left_day, right_day


def _parse_side_tokens(tokens, side, left_day, right_day, day_pairs):
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if DAY_RE.match(token):
            day_num = int(token)
            left_day, right_day = _update_day(day_num, side, left_day, right_day)
            index += 1
            continue

        if (
            TIME_RE.match(token)
            and index + 1 < len(tokens)
            and HEIGHT_RE.match(tokens[index + 1])
        ):
            current_day = left_day if side == "left" else right_day
            if current_day is not None:
                day_pairs.setdefault(current_day, []).append(
                    (_format_time(token), float(tokens[index + 1]))
                )
            index += 2
            if index < len(tokens) and TIDE_LETTER_RE.match(tokens[index]):
                index += 1
            continue

        index += 1

    return left_day, right_day


def parse_port_pdf(pdf_bytes, year, month):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    midpoint = page.rect.width / 2

    rows = defaultdict(lambda: {"left": [], "right": []})
    for word in page.get_text("words"):
        x0, y0, *_rest, text = word[0], word[1], word[2], word[3], word[4]
        side = "left" if x0 < midpoint else "right"
        rows[round(y0)][side].append((x0, text))

    left_day = None
    right_day = 16
    day_pairs = {}

    for y_pos in sorted(rows):
        left_tokens = [text for _, text in sorted(rows[y_pos]["left"])]
        right_tokens = [text for _, text in sorted(rows[y_pos]["right"])]
        left_day, right_day = _parse_side_tokens(
            left_tokens, "left", left_day, right_day, day_pairs
        )
        left_day, right_day = _parse_side_tokens(
            right_tokens, "right", left_day, right_day, day_pairs
        )

    events = []
    for day_num, pairs in sorted(day_pairs.items()):
        date_str = f"{year}-{month:02d}-{day_num:02d}"
        for tide_type, time_str, height in _classify_tides_for_day(pairs):
            events.append(
                {
                    "date": date_str,
                    "time": time_str,
                    "height_m": round(height, 2),
                    "type": tide_type,
                }
            )

    events.sort(key=lambda item: (item["date"], item["time"]))
    return events
