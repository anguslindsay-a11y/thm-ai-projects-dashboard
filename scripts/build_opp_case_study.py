"""
Build the Off Page (OPP & Bookmarks) Sales Case Study PDF.
Mirrors the brand and layout of [C] Case Study - Outdoor Living (Sales) Final - Template.pdf.

Run from project root:
    python scripts/build_opp_case_study.py
"""

from pathlib import Path

from reportlab.lib.colors import HexColor, Color
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HOME = Path("C:/Users/MasenSpring/OneDrive - TheHomeMagWest")
CASE_STUDIES = HOME / "Cowork Homebase/02 Projects/THM Media - Client Work/Case Studies"
IMAGES = CASE_STUDIES / "Image Files"
OUT_PDF = CASE_STUDIES / "[C] Case Study - Off Page (Sales).pdf"

LOGO_WHITE = IMAGES / "PrimaryLogo_01.png"
CERTIFIED_BADGE = IMAGES / "Certified-Badge-5K-Guarantee-blue.png"
ASKHOMEY_IMG = IMAGES / "Zion Outdoors-THMTX-FC-AUN-2511.jpg"  # placeholder/sample

# Fonts we ship in the workspace + Chrome extension fallback
FONT_DIR_PRIMARY = HOME / "Streamlit Dashboard/fonts"
FONT_DIR_FALLBACK = (
    HOME.parent
    / "MasenSpring/AppData/Local/Google/Chrome/User Data/Profile 1/Extensions"
    / "fheoggkfdfchfphceeifdbepaooicaho/8.1.0.8996_0/fonts"
)


def _register_font(name: str, candidates: list[Path]) -> str:
    """Register the first available TTF; return the registered name (or Helvetica fallback)."""
    for path in candidates:
        if path.exists():
            try:
                pdfmetrics.registerFont(TTFont(name, str(path)))
                return name
            except Exception:  # noqa: BLE001
                continue
    return "Helvetica"


HEAD_BOLD = _register_font(
    "Poppins-Bold",
    [FONT_DIR_PRIMARY / "Poppins-Bold.ttf", FONT_DIR_FALLBACK / "Poppins-Bold.ttf"],
)
HEAD_SEMI = _register_font(
    "Poppins-SemiBold",
    [FONT_DIR_FALLBACK / "Poppins-SemiBold.ttf", FONT_DIR_PRIMARY / "Poppins-Bold.ttf"],
)
HEAD_REG = _register_font(
    "Poppins-Regular",
    [FONT_DIR_PRIMARY / "Poppins-Regular.ttf", FONT_DIR_FALLBACK / "Poppins-Regular.ttf"],
)
HEAD_LIGHT = _register_font(
    "Poppins-Light",
    [FONT_DIR_FALLBACK / "Poppins-Light.ttf", FONT_DIR_PRIMARY / "Poppins-Regular.ttf"],
)
BODY = "Helvetica"
BODY_BOLD = "Helvetica-Bold"
BODY_ITAL = "Helvetica-Oblique"

# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------
INDIGO = HexColor("#223a5c")
MAASTRICHT = HexColor("#0d2038")
CADET = HexColor("#a2b4c0")
TIMBERWOLF = HexColor("#d9d4d0")
PALE_BG = HexColor("#f0f3f6")
WHITE = HexColor("#ffffff")
GRAY_TEXT = HexColor("#4a5562")
LIGHT_TEXT = HexColor("#cbd4dd")

PAGE_W, PAGE_H = LETTER  # 612 x 792


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fill_rect(c: canvas.Canvas, x, y, w, h, color):
    c.setFillColor(color)
    c.setStrokeColor(color)
    c.rect(x, y, w, h, stroke=0, fill=1)


def draw_text(c: canvas.Canvas, x, y, text, font, size, color, anchor="left"):
    c.setFont(font, size)
    c.setFillColor(color)
    if anchor == "center":
        c.drawCentredString(x, y, text)
    elif anchor == "right":
        c.drawRightString(x, y, text)
    else:
        c.drawString(x, y, text)


def wrap_lines(c: canvas.Canvas, text: str, font: str, size: float, max_w: float) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines, cur = [], words[0]
    for w in words[1:]:
        trial = cur + " " + w
        if c.stringWidth(trial, font, size) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def draw_paragraph(c, x, y, text, font, size, color, max_w, leading):
    """Draw paragraph from top-left at (x, y); return new y after last line."""
    lines = wrap_lines(c, text, font, size, max_w)
    cy = y
    for line in lines:
        draw_text(c, x, cy, line, font, size, color)
        cy -= leading
    return cy + leading  # last baseline


def draw_image_fit(c, path: Path, x, y, w, h, mask=None):
    """Draw image fit-within (preserve aspect, no crop) inside box (x,y,w,h)."""
    if not path.exists():
        return
    try:
        img = ImageReader(str(path))
        iw, ih = img.getSize()
        scale = min(w / iw, h / ih)
        dw, dh = iw * scale, ih * scale
        dx = x + (w - dw) / 2
        dy = y + (h - dh) / 2
        c.drawImage(img, dx, dy, dw, dh, mask=mask, preserveAspectRatio=True)
    except Exception:  # noqa: BLE001
        pass


def header_bar(c, page_label: str):
    """Maastricht header bar with category label + logo."""
    bar_h = 58
    bar_y = PAGE_H - bar_h
    fill_rect(c, 0, bar_y, PAGE_W, bar_h, MAASTRICHT)

    # left text
    draw_text(c, 36, bar_y + bar_h - 22, "CASE STUDY", HEAD_SEMI, 7.5, CADET)
    draw_text(c, 36, bar_y + bar_h - 42, page_label, HEAD_BOLD, 20, WHITE)

    # right logo
    if LOGO_WHITE.exists():
        draw_image_fit(c, LOGO_WHITE, PAGE_W - 36 - 140, bar_y + 12, 140, 36, mask="auto")

    # accent stripe
    fill_rect(c, 0, bar_y - 3, PAGE_W, 3, CADET)


def footer_bar(c):
    bar_h = 64
    fill_rect(c, 0, 0, PAGE_W, bar_h, MAASTRICHT)
    draw_text(
        c,
        PAGE_W / 2,
        bar_h - 14,
        "Contact your media advisor or reach out to TheHomeMag directly:",
        HEAD_REG,
        8.5,
        CADET,
        anchor="center",
    )
    # 2 rows × 2 columns, single inline string per cell
    contacts = [
        ("CO", "(303) 220-4242", "marketing.co@thmmedia.com"),
        ("UT", "(801) 410-4666", "marketing.ut@thmmedia.com"),
        ("AU", "(512) 271-5488", "marketing.au@thmmedia.com"),
        ("SA", "(210) 444-9346", "marketing.sa@thmmedia.com"),
    ]
    col_x = [PAGE_W * 0.27, PAGE_W * 0.73]
    for i, (market, phone, email) in enumerate(contacts):
        col = col_x[i % 2]
        row = 1 - (i // 2)  # 0 (bottom), 1 (top)
        ty = 12 + row * 16
        # market badge + line
        line = f"{market}   {phone}   ·   {email}"
        # render badge separately for emphasis
        badge_w = c.stringWidth(market, HEAD_SEMI, 8.5)
        rest = f"   {phone}   ·   {email}"
        rest_w = c.stringWidth(rest, BODY, 7.5)
        total = badge_w + rest_w
        sx = col - total / 2
        draw_text(c, sx, ty, market, HEAD_SEMI, 8.5, WHITE)
        draw_text(c, sx + badge_w, ty, rest, BODY, 7.5, LIGHT_TEXT)


# ---------------------------------------------------------------------------
# Page 1
# ---------------------------------------------------------------------------
def page_one(c):
    header_bar(c, "OFF PAGE PLACEMENTS")

    # Hero band
    hero_h = 76
    hero_y = PAGE_H - 58 - 3 - hero_h
    fill_rect(c, 0, hero_y, PAGE_W, hero_h, INDIGO)
    draw_text(
        c,
        PAGE_W / 2,
        hero_y + hero_h - 28,
        "OFF PAGE PLACEMENTS DON'T GET TURNED PAST. THEY GET KEPT.",
        HEAD_BOLD,
        14,
        WHITE,
        anchor="center",
    )
    draw_text(
        c,
        PAGE_W / 2,
        hero_y + 22,
        "PopOuts and Bookmark Cards live on the fridge, in the planner, and on the phone — here's the proof.",
        HEAD_REG,
        10.5,
        CADET,
        anchor="center",
    )

    # Intro strip
    intro_h = 68
    intro_y = hero_y - intro_h
    fill_rect(c, 0, intro_y, PAGE_W, intro_h, WHITE)
    intro_txt = (
        "Off Page (OPP) placements — PopOuts and Bookmark Cards — sit on TheHomeMag's most-handled "
        "real estate. They get pulled out, kept, scanned, and called weeks after the magazine first "
        "lands. Colorado advertisers have built renewable, year-round programs around them. The data "
        "below shows exactly what that looks like."
    )
    draw_paragraph(
        c,
        36,
        intro_y + intro_h - 18,
        intro_txt,
        BODY,
        9,
        GRAY_TEXT,
        max_w=PAGE_W - 72,
        leading=12,
    )

    # divider
    fill_rect(c, 36, intro_y - 1, PAGE_W - 72, 0.7, CADET)

    # Two columns body
    body_top = intro_y - 12
    body_bottom = 64 + 86 + 8  # footer + digital strip + gap
    body_h = body_top - body_bottom
    left_x = 36
    left_w = 272
    right_x = left_x + left_w + 24
    right_w = PAGE_W - right_x - 36

    # ---- LEFT COLUMN ----
    cy = body_top - 4
    draw_text(c, left_x, cy, "WHY OFF PAGE WORKS", HEAD_BOLD, 11, INDIGO)
    cy -= 14
    draw_text(
        c,
        left_x,
        cy,
        "High-performing OPP advertisers invest in:",
        BODY_ITAL,
        8.5,
        GRAY_TEXT,
    )
    cy -= 14

    products = [
        (
            "OPP PopOuts",
            "Tear-out, keep-with-you cards homeowners save and act on later.",
        ),
        (
            "Bookmark Cards",
            "Premium magnet-strip placements that stay on the fridge for months.",
        ),
        (
            "High-Intent Repetition",
            "Same audience, every issue — building brand familiarity at the moment of decision.",
        ),
        (
            "Multi-Channel Attribution",
            "Calls, QR scans, and email clicks track every lead the placement generates.",
        ),
    ]
    for title, desc in products:
        # cadet dot
        c.setFillColor(CADET)
        c.circle(left_x + 4, cy - 1, 2.5, stroke=0, fill=1)
        draw_text(c, left_x + 14, cy, title, HEAD_SEMI, 9.5, INDIGO)
        cy -= 12
        for line in wrap_lines(c, desc, BODY, 8.5, left_w - 14):
            draw_text(c, left_x + 14, cy, line, BODY, 8.5, GRAY_TEXT)
            cy -= 11
        cy -= 5

    cy -= 4
    impact = (
        "The result: a small core of CO clients renew month after month — because Off Page "
        "keeps working long after the magazine hits the mailbox."
    )
    cy = draw_paragraph(c, left_x, cy, impact, BODY_BOLD, 9, INDIGO, left_w, 12) - 14

    # certified badge
    if CERTIFIED_BADGE.exists():
        draw_image_fit(c, CERTIFIED_BADGE, left_x, cy - 56, 60, 56, mask="auto")

    # ---- RIGHT COLUMN: Stat callouts ----
    draw_text(
        c,
        right_x + right_w / 2,
        body_top - 4,
        "THE NUMBERS BEHIND OPP",
        HEAD_BOLD,
        11,
        INDIGO,
        anchor="center",
    )
    draw_text(
        c,
        right_x + right_w / 2,
        body_top - 18,
        "CO PERFORMANCE · LAST 18 MONTHS",
        HEAD_SEMI,
        7,
        CADET,
        anchor="center",
    )

    # 2x2 stat grid
    stats = [
        ("853", "QR SCANS", "Apex Clean Air — Bookmarks scanned over a 12-month run.", PALE_BG, INDIGO),
        ("286", "QUALIFIED CALLS", "Lawn Doctor of Denver — biggest call lift in our book.", INDIGO, WHITE),
        ("73%", "QUALIFIED RATE", "Premier Custom Decks — 78 of 107 calls were 60+ seconds.", MAASTRICHT, WHITE),
        ("16+", "MONTHS RUNNING", "Woodley's Furniture — Bookmarks every issue, booked through 2026.", CADET, INDIGO),
    ]
    grid_top = body_top - 32
    grid_bot = body_bottom + 10
    grid_h = grid_top - grid_bot
    cell_w = (right_w - 8) / 2
    cell_h = (grid_h - 8) / 2
    for idx, (big, label, sub, fill, fg) in enumerate(stats):
        col = idx % 2
        row = idx // 2
        bx = right_x + col * (cell_w + 8)
        by = grid_top - (row + 1) * cell_h - row * 8
        fill_rect(c, bx, by, cell_w, cell_h, fill)
        draw_text(c, bx + cell_w / 2, by + cell_h - 38, big, HEAD_BOLD, 38, fg, anchor="center")
        draw_text(
            c,
            bx + cell_w / 2,
            by + cell_h - 56,
            label,
            HEAD_SEMI,
            8.5,
            CADET if fill in (INDIGO, MAASTRICHT) else INDIGO,
            anchor="center",
        )
        # description
        sub_lines = wrap_lines(c, sub, BODY_ITAL, 7.5, cell_w - 16)
        sy = by + 22
        for line in sub_lines:
            draw_text(c, bx + cell_w / 2, sy, line, BODY_ITAL, 7.5, fg, anchor="center")
            sy -= 10

    # ---- DIGITAL STRIP ----
    strip_h = 86
    strip_y = 64
    fill_rect(c, 0, strip_y, PAGE_W, strip_h, PALE_BG)

    # left text block
    draw_text(c, 36, strip_y + strip_h - 18, "EXTEND YOUR REACH ONLINE", HEAD_BOLD, 10.5, INDIGO)
    digital_body = (
        "Print drives recognition. Digital keeps you there. TheHomeMag's email and AskHomey "
        "touchpoints reach the same homeowners who pulled out your OPP card — when they're "
        "actively searching and ready to buy."
    )
    draw_paragraph(
        c, 36, strip_y + strip_h - 32, digital_body, BODY, 8.5, GRAY_TEXT, max_w=240, leading=11
    )

    # center: Inbox Advantage placeholder
    box_w, box_h = 140, 60
    box_x = 36 + 250
    box_y = strip_y + (strip_h - box_h) / 2
    c.setStrokeColor(CADET)
    c.setDash(3, 2)
    c.setLineWidth(1)
    c.rect(box_x, box_y, box_w, box_h, stroke=1, fill=0)
    c.setDash()
    draw_text(
        c,
        box_x + box_w / 2,
        box_y + box_h / 2 + 6,
        "INBOX ADVANTAGE",
        HEAD_SEMI,
        8.5,
        INDIGO,
        anchor="center",
    )
    draw_text(
        c,
        box_x + box_w / 2,
        box_y + box_h / 2 - 6,
        "Targeted Email",
        BODY_ITAL,
        8,
        GRAY_TEXT,
        anchor="center",
    )

    # right: AskHomey image
    ah_w, ah_h = 100, 60
    ah_x = PAGE_W - 36 - ah_w
    ah_y = strip_y + (strip_h - ah_h) / 2
    if ASKHOMEY_IMG.exists():
        draw_image_fit(c, ASKHOMEY_IMG, ah_x, ah_y, ah_w, ah_h)
    # label overlay
    fill_rect(c, ah_x, ah_y, ah_w, 14, MAASTRICHT)
    draw_text(c, ah_x + ah_w / 2, ah_y + 4, "ASKHOMEY.COM", HEAD_SEMI, 7, WHITE, anchor="center")

    footer_bar(c)


# ---------------------------------------------------------------------------
# Page 2
# ---------------------------------------------------------------------------
def page_two(c):
    header_bar(c, "OFF PAGE PLACEMENTS")

    # banner
    banner_h = 56
    banner_y = PAGE_H - 58 - 3 - banner_h
    fill_rect(c, 0, banner_y, PAGE_W, banner_h, INDIGO)
    draw_text(
        c,
        PAGE_W / 2,
        banner_y + banner_h - 22,
        "THE PROOF IS IN THE CALLS — AND THE SCANS",
        HEAD_BOLD,
        17,
        WHITE,
        anchor="center",
    )
    draw_text(
        c,
        PAGE_W / 2,
        banner_y + 12,
        "How three Colorado advertisers turn Off Page visibility into measurable leads",
        HEAD_LIGHT,
        9.5,
        CADET,
        anchor="center",
    )
    fill_rect(c, 0, banner_y - 2, PAGE_W, 2, CADET)

    # Three tier rows
    tiers = [
        {
            "tag": "SOLID START",
            "tag_color": CADET,
            "tag_text": INDIGO,
            "row_bg": WHITE,
            "stat_color": CADET,
            "stat_text": INDIGO,
            "client": "Premier Custom Decks",
            "bullets": [
                "South Denver · Decks & Outdoor Living",
                "14 OPP PopOuts running March 2025 – October 2026",
                "78 of 107 inbound calls were 60+ seconds — a 73% qualified rate",
            ],
            "roi": "Decks audience matches OPP perfectly — high-intent buyers ready to talk projects.",
            "stat_big": "78",
            "stat_label": "QUALIFIED CALLS",
            "insight": "\"Three of four CO deck companies that have tried OPP are still on it a year-plus later.\"",
        },
        {
            "tag": "GROWING FAST",
            "tag_color": INDIGO,
            "tag_text": WHITE,
            "row_bg": PALE_BG,
            "stat_color": INDIGO,
            "stat_text": WHITE,
            "client": "Lawn Doctor of Denver",
            "bullets": [
                "Denver Metro · Landscaping",
                "32 OPP placements (28 PopOut + 4 Bookmark) over 14 months",
                "509 total inbound calls during the OPP run window",
            ],
            "roi": "No CO advertiser has driven more qualified phone volume from Off Page.",
            "stat_big": "286",
            "stat_label": "QUALIFIED CALLS",
            "insight": "\"Off Page rings the phone. The cleanest 'OPP drives the phone' story we have.\"",
        },
        {
            "tag": "MARKET LEADER",
            "tag_color": MAASTRICHT,
            "tag_text": WHITE,
            "row_bg": WHITE,
            "stat_color": MAASTRICHT,
            "stat_text": WHITE,
            "client": "Apex Clean Air",
            "bullets": [
                "Denver Metro · HVAC & Plumbing (Air Duct Cleaning)",
                "25 OPP PopOuts every issue — January 2025 through December 2026",
                "No CallRail — QR scans and email clicks carry full attribution",
            ],
            "roi": "Even untracked clients prove OPP works — the Bookmark format gets kept and scanned.",
            "stat_big": "853",
            "stat_label": "QR SCANS",
            "insight": "\"Liberty Home Products tells the same story: 833 scans on a 12-month PopOut run.\"",
        },
    ]

    row_h = 96
    gap = 5
    rows_top = banner_y - 12
    cur_y = rows_top - row_h

    for tier in tiers:
        # row bg
        fill_rect(c, 0, cur_y, PAGE_W, row_h, tier["row_bg"])

        # left tag strip
        tag_w = 70
        fill_rect(c, 0, cur_y, tag_w, row_h, tier["tag_color"])
        # accent on right edge
        fill_rect(c, tag_w - 2, cur_y, 2, row_h, CADET)
        # rotated label
        c.saveState()
        c.translate(tag_w / 2, cur_y + row_h / 2)
        c.rotate(90)
        draw_text(c, 0, -3, tier["tag"], HEAD_BOLD, 11, tier["tag_text"], anchor="center")
        c.restoreState()

        # right stat zone
        stat_w = 130
        stat_x = PAGE_W - stat_w
        fill_rect(c, stat_x, cur_y, stat_w, row_h, tier["stat_color"])
        draw_text(
            c,
            stat_x + stat_w / 2,
            cur_y + row_h - 38,
            tier["stat_big"],
            HEAD_BOLD,
            32,
            tier["stat_text"],
            anchor="center",
        )
        draw_text(
            c,
            stat_x + stat_w / 2,
            cur_y + row_h - 50,
            tier["stat_label"],
            HEAD_SEMI,
            7,
            tier["stat_text"],
            anchor="center",
        )
        # insight quote
        ins_lines = wrap_lines(c, tier["insight"], BODY_ITAL, 6.5, stat_w - 14)
        iy = cur_y + 32
        for line in ins_lines[:4]:
            draw_text(
                c,
                stat_x + stat_w / 2,
                iy,
                line,
                BODY_ITAL,
                6.5,
                tier["stat_text"],
                anchor="center",
            )
            iy -= 8.5

        # middle zone
        mx = tag_w + 14
        my = cur_y + row_h - 16
        # client name
        draw_text(c, mx, my, tier["client"], HEAD_BOLD, 11.5, INDIGO)
        my -= 14
        # bullets
        max_bullet_w = PAGE_W - tag_w - stat_w - 50
        for b in tier["bullets"]:
            c.setFillColor(CADET)
            c.circle(mx + 3, my - 1, 2.2, stroke=0, fill=1)
            lines = wrap_lines(c, b, BODY, 8, max_bullet_w)
            for i, line in enumerate(lines):
                draw_text(c, mx + 11, my - i * 9.5, line, BODY, 8, GRAY_TEXT)
            my -= 10 + (len(lines) - 1) * 9.5
        # roi line
        roi_y = cur_y + 12
        for line in wrap_lines(c, tier["roi"], BODY_ITAL, 8, PAGE_W - tag_w - stat_w - 30):
            draw_text(c, mx, roi_y, line, BODY_ITAL, 8, INDIGO)
            roi_y -= 10

        cur_y -= row_h + gap

    # ---- BOTTOM SECTION ----
    bottom_top = cur_y - 4
    footer_top = 64
    bottom_h = bottom_top - footer_top - 8

    left_w = (PAGE_W - 72) * 0.54 - 8
    left_x = 36
    right_x = left_x + left_w + 16
    right_w = PAGE_W - 36 - right_x

    # LEFT — why these companies win
    by = bottom_top - 4
    draw_text(c, left_x, by, "WHY THESE COMPANIES WIN", HEAD_BOLD, 11.5, INDIGO)
    by -= 6
    fill_rect(c, left_x, by, left_w, 0.8, CADET)
    by -= 14

    why = [
        (
            "They commit to repetition.",
            "Every top OPP performer in the book runs every issue. The format compounds — homeowners save the card, then call weeks later.",
        ),
        (
            "They match the placement to the buyer.",
            "High-ticket categories — decks, HVAC, landscaping, roofing — where homeowners research, save info, and call back when they're ready.",
        ),
        (
            "They track everything.",
            "Calls, QR scans, email clicks. Multi-channel attribution proves the program is working — even when CallRail isn't in the mix.",
        ),
    ]
    for label, expl in why:
        c.setFillColor(CADET)
        c.circle(left_x + 4, by - 1, 2.5, stroke=0, fill=1)
        draw_text(c, left_x + 14, by, label, HEAD_BOLD, 9, INDIGO)
        by -= 12
        for line in wrap_lines(c, expl, BODY, 8.5, left_w - 14):
            draw_text(c, left_x + 14, by, line, BODY, 8.5, GRAY_TEXT)
            by -= 11
        by -= 6

    # RIGHT — CTA box
    fill_rect(c, right_x, footer_top + 8, right_w, 5, CADET)
    cta_y = footer_top + 8 + 5
    cta_h = bottom_top - cta_y
    fill_rect(c, right_x, cta_y, right_w, cta_h, MAASTRICHT)

    cy = cta_y + cta_h - 22
    head_lines = wrap_lines(
        c,
        "Ready to Add Off Page to Your Program?",
        HEAD_BOLD,
        13,
        right_w - 32,
    )
    for line in head_lines:
        draw_text(c, right_x + 16, cy, line, HEAD_BOLD, 13, WHITE)
        cy -= 16
    cy -= 4
    fill_rect(c, right_x + 16, cy + 4, right_w - 32, 0.7, CADET)
    cy -= 12

    body_txt = (
        "From 286 qualified calls in just over a year to 853 QR scans on a single Bookmark run, "
        "the proof is in Colorado. Deck builders, HVAC shops, landscapers, and roofers in UT and "
        "TX can run the same playbook. Your phone — and your inbox — should be next."
    )
    for line in wrap_lines(c, body_txt, BODY, 9, right_w - 32):
        draw_text(c, right_x + 16, cy, line, BODY, 9, LIGHT_TEXT)
        cy -= 12

    cy -= 6
    draw_text(
        c,
        right_x + 16,
        cy,
        "Let's build your program.",
        HEAD_SEMI,
        10,
        CADET,
    )

    footer_bar(c)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT_PDF), pagesize=LETTER)
    c.setTitle("THM Media — Off Page Case Study (Sales)")
    c.setAuthor("THM Media")
    page_one(c)
    c.showPage()
    page_two(c)
    c.showPage()
    c.save()
    print(f"Wrote {OUT_PDF}")


if __name__ == "__main__":
    main()
