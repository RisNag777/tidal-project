"""Shared WhatsApp action-section helpers."""

WHATSAPP_MAX_CHARS = 1500


def earliest_marker_index(text, markers):
    cut_at = None
    for marker in markers:
        idx = text.find(marker)
        if idx != -1 and (cut_at is None or idx < cut_at):
            cut_at = idx
    return cut_at


def format_landmark_list(landmarks):
    landmarks = [str(item).strip() for item in landmarks if str(item).strip()]
    if not landmarks:
        return ""
    if len(landmarks) == 1:
        return landmarks[0]
    if len(landmarks) == 2:
        return f"{landmarks[0]} and {landmarks[1]}"
    return ", ".join(landmarks[:-1]) + f", and {landmarks[-1]}"


def parse_audience(user_text, audience_aliases):
    clean = " ".join((user_text or "").lower().split())
    if not clean:
        return None
    candidates = []
    for audience, aliases in audience_aliases.items():
        for alias in aliases:
            candidates.append((len(alias), alias, audience))
    candidates.sort(reverse=True)
    for _length, alias, audience in candidates:
        if alias in clean:
            return audience
    return None


def truncate_for_whatsapp(text, limit=WHATSAPP_MAX_CHARS):
    if len(text) <= limit:
        return text
    suffix = "\n\n…(shortened) Stay safe."
    keep = limit - len(suffix)
    trimmed = text[:keep].rsplit("\n", 1)[0].rstrip()
    print(f"⚠️ Truncated advisory from {len(text)} to ≤{limit} chars for WhatsApp")
    return trimmed + suffix


def apply_action_templates(
    advisory,
    sections,
    emergency_line,
    cut_markers,
):
    """Attach prebuilt action sections and emergency footer to conditions text."""
    closing = "Stay safe.\n\n" + emergency_line
    cut_at = earliest_marker_index(advisory, cut_markers)
    stay_idx = advisory.rfind("Stay safe.")
    if cut_at is not None and stay_idx != -1 and cut_at < stay_idx:
        return advisory[:cut_at].rstrip() + "\n\n" + sections + "\n\n" + closing
    if stay_idx != -1:
        return advisory[:stay_idx].rstrip() + "\n\n" + sections + "\n\n" + closing
    return advisory.rstrip() + "\n\n" + sections + "\n\n" + closing
