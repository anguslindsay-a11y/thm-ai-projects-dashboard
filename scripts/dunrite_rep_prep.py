"""Generate a rep-prep PDF for the Dun-Rite Kitchens & Baths meeting.

Worded so it can be shown directly to the client if needed. Contains:
  1. Dun-Rite's current footprint
  2. Dun-Rite's full monthly campaign breakdown (last 12 months)
  3. Comparable CO performers in Kitchen & Bath, Windows & Doors, and Basements
     (12-month rolling and 2026 YTD), with distribution + ad size in place of
     competitor spend
  4. Key Points — observations the rep can lean on
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

REPO = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO / "output"


# ----- Dun-Rite footprint -----
DUNRITE_FOOTPRINT = {
    "category": "Kitchen & Bath Remodeling",
    "market": "CO (Colorado) — all 4 zones (EPC, ND, NOCO, SD)",
    "distribution": "380,000 households per issue (full CO coverage)",
    "spend_12mo": "$115,794 (last 12 months)",
    "spend_ytd": "$69,970 (2026 YTD)",
    "call_tracking": "Not enrolled in CallRail",
    "email": "10 Inbox Advantage campaigns / 8,667 clicks (12 mo)",
    "products": ("1/2 Page (all 4 zones, every month) plus Full Page, Double Page, "
                 "OPP PopOut, Full Page DirSpot, and zone Exclusive/Sponsored "
                 "placements added beginning Jan 2026"),
}


# ----- Dun-Rite full monthly campaign breakdown (last 12 months) -----
# Cells: EPC | ND | NOCO | SD | Other | Total spend
DUNRITE_MONTHLY = [
    # issue, EPC, ND, NOCO, SD, Other, total
    ("May 2025",   "1/2 Page", "1/2 Page", "1/2 Page", "1/2 Page", "Directory Listing", "$5,728"),
    ("Jun 2025",   "1/2 Page", "1/2 Page", "1/2 Page", "1/2 Page", "Directory Listing", "$5,728"),
    ("Jul 2025",   "1/2 Page", "1/2 Page", "1/2 Page", "1/2 Page", "Directory Listing", "$5,728"),
    ("Aug 2025",   "1/2 Page", "1/2 Page", "1/2 Page", "1/2 Page", "Directory Listing", "$5,728"),
    ("Sep 2025",   "1/2 Page", "1/2 Page", "1/2 Page", "1/2 Page", "Directory Listing", "$5,728"),
    ("Oct 2025",   "1/2 Page", "1/2 Page", "1/2 Page", "1/2 Page", "Directory Listing", "$5,728"),
    ("Nov 2025",   "1/2 Page", "1/2 Page", "1/2 Page", "1/2 Page", "Directory Listing", "$5,728"),
    ("Dec 2025",   "1/2 Page", "1/2 Page", "1/2 Page", "1/2 Page", "Directory Listing", "$5,728"),
    ("Jan 2026",   "1/2 Page + EPC Exclusive 01",
                   "1/2 Page (×2) + Full Page + ND Sponsored 01",
                   "1/2 Page",
                   "Double Page + SD Sponsored 01",
                   "Directory Listing", "$12,285"),
    ("Feb 2026",   "1/2 Page + Full Page DirSpot + EPC Sponsored 01",
                   "Full Page + Full Page DirSpot + ND Sponsored 01 + OPP PopOut",
                   "1/2 Page + NoCO Exclusive 01",
                   "1/2 Page (×2) + Full Page + SD Exclusive 01",
                   "Directory Listing", "$23,563"),
    ("Mar 2026",   "1/2 Page + EPC Sponsored 02",
                   "Double Page + ND Exclusive 01",
                   "1/2 Page",
                   "Full Page + Full Page DirSpot + OPP PopOut + SD Sponsored 01",
                   "Directory Listing", "$21,873"),
    ("Apr Spring 2026", "1/2 Page", "1/2 Page", "1/2 Page", "1/2 Page", "Directory Listing", "$6,114"),
    ("Apr 2026",        "1/2 Page", "1/2 Page", "1/2 Page", "1/2 Page", "Directory Listing", "$6,135"),
]


# ----- Top performers — last 12 months -----
# Columns: client, distribution, zones, ad size, total_calls, qual, missed, qr, email
KB_12MO = [
    ("ReNew Home Innovations",            "380K", "EPC, ND, NOCO, SD", "Full Page",                              "255", "165", "11", "157", "0 / 0"),
    ("MaK Construction",                  "120K", "SD",                "Double Page + Front Cover",              "59",  "42",  "3",  "38",  "6 / 7,260"),
    ("Build A Bath",                      "220K", "ND, SD",            "Full Page + Back Cover 2/3",             "68",  "33",  "17", "25",  "5 / 5,397"),
    ("Home Improvement Express - NoCO",   "80K",  "NOCO",              "1/2 Page",                               "140", "102", "7",  "0",   "13 / 10,006"),
    ("Planet Granite",                    "200K", "EPC, SD",           "Full Page + Front Cover + Back Cover 2/3","117", "57",  "7",  "0",   "0 / 0"),
    ("SimplySinks (Alpine Summit)",       "220K", "ND, SD",            "1/2 Page",                               "95",  "46",  "1",  "0",   "1 / 934"),
]

KB_YTD = [
    ("ReNew Home Innovations",            "380K", "EPC, ND, NOCO, SD", "Full Page",                              "91",  "61",  "2", "40",  "0 / 0"),
    ("MaK Construction",                  "120K", "SD",                "Double Page + Front Cover",              "12",  "10",  "1", "14",  "2 / 2,200"),
    ("Planet Granite",                    "200K", "EPC, SD",           "Full Page + Front Cover + Back Cover 2/3","31",  "15",  "2", "0",   "0 / 0"),
    ("SimplySinks (Alpine Summit)",       "220K", "ND, SD",            "1/2 Page",                               "56",  "31",  "1", "0",   "0 / 0"),
    ("Home Improvement Express - S Denver","120K","SD",                "1/2 Page",                               "26",  "14",  "2", "0",   "4 / 3,274"),
    ("Build A Bath",                      "120K", "SD",                "Full Page + Back Cover 2/3",             "16",  "12",  "2", "14",  "0 / 0"),
]

WD_12MO = [
    # True windows/doors installation comparables — excludes window cleaning, window wells,
    # outdoor living, decks, blinds, and national RBA cross-market records.
    ("Bellwether Windows, Siding & Doors", "300K", "ND, NOCO, SD", "Full Page + Front Cover", "95",  "57",  "3", "18", "3 / 1,926"),
    ("City Glass Company, Inc",            "80K",  "EPC",          "Full Page + Front Cover", "197", "133", "5", "6",  "2 / 1,698"),
    ("Pikes Peak Overhead Door",           "80K",  "EPC",          "1/2 Page",                "168", "129", "1", "0",  "1 / 884"),
    ("One Day Doors & Closets",            "80K",  "EPC",          "Full Page + Back Cover Banner", "37",  "18",  "3", "0",  "3 / 1,953"),
    ("The Door Dudes",                     "180K", "ND, NOCO",     "Full Page",               "35",  "23",  "1", "65", "0 / 0"),
    ("Peakview Windows & Siding",          "80K",  "EPC",          "1/2 Page",                "48",  "36",  "2", "0",  "0 / 0"),
]

WD_YTD = [
    ("Bellwether Windows, Siding & Doors", "180K", "ND, NOCO", "Full Page + Front Cover",    "19", "12", "1", "14", "3 / 1,926"),
    ("One Day Doors & Closets",            "80K",  "EPC",      "Full Page + Back Cover Banner", "3",  "3",  "0", "0",  "2 / 972"),
    ("Pikes Peak Overhead Door",           "80K",  "EPC",      "1/2 Page",                   "49", "45", "0", "0",  "1 / 884"),
    ("City Glass Company, Inc",            "80K",  "EPC",      "Full Page + Front Cover",    "61", "50", "3", "0",  "1 / 719"),
    ("Peakview Windows & Siding",          "80K",  "EPC",      "1/2 Page",                   "13", "10", "1", "0",  "0 / 0"),
    ("The Door Dudes",                     "180K", "ND, NOCO", "Full Page",                  "5",  "4",  "0", "27", "0 / 0"),
]

BASEMENT_12MO = [
    ("Basement Finishers",     "220K", "ND, SD", "Full Page",   "125", "60", "16", "0", "0 / 0"),
    ("Wood Road Construction", "80K",  "EPC",    "Double Page", "52",  "25", "5",  "0", "4 / 3,473"),
]

BASEMENT_YTD = [
    ("Basement Finishers",     "220K", "ND, SD", "Full Page",   "24", "15", "1", "0", "0 / 0"),
    ("Wood Road Construction", "80K",  "EPC",    "Double Page", "16", "5",  "2", "0", "0 / 0"),
]


# ----- Key Points -----
KEY_POINTS = [
    ("Topic", "Detail"),
    ("Category benchmark",
     "ReNew Home Innovations runs an essentially identical footprint to Dun-Rite — full "
     "380K CO distribution across all 4 zones — and pulled 165 qualified calls plus 157 "
     "QR scans over 12 months. The K&amp;B audience is producing in CO."),
    ("Print performance",
     "Home Improvement Express (4 zone records combined) delivered 338 qualified calls + "
     "~39K email clicks across 380K total distribution over 12 months. In Windows &amp; "
     "Doors, Bellwether (300K distribution, Full Page + Front Cover) generated 57 qualified "
     "calls + 1,926 email clicks — print + digital engagement compounding."),
    ("Distribution strategy",
     "Dun-Rite's 380K full-CO distribution puts them in the top tier of K&amp;B "
     "advertisers in our book. Other 380K-distribution clients (ReNew, Yearmark, Egress) "
     "consistently outperform single-zone players in absolute lead volume."),
    ("Email engagement",
     "Dun-Rite averages ~867 clicks per IA campaign — middle of the K&amp;B pack. Top "
     "performers in the bucket: MaK Construction (1,210/campaign), Build A Bath "
     "(1,079/campaign). Closeable gap with creative refresh."),
    ("2026 expansion",
     "Dun-Rite's January 2026 footprint expanded substantially — adding Full Pages, Double "
     "Pages, OPP PopOuts, and zone Exclusive/Sponsored placements on top of the steady "
     "1/2 Page across all zones. Q1 2026 spend was ~$58K vs ~$23K in Q4 2025."),
    ("Adjacency opportunity",
     "Basement Finishing &amp; Remodeling has only 2 active CO competitors. If Dun-Rite "
     "ever wants to test category expansion, the bucket is wide open."),
]


# ----- Styles -----
styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=18, spaceAfter=8,
                    textColor=colors.HexColor("#1F4E78"))
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, spaceAfter=4,
                    textColor=colors.HexColor("#1F4E78"))
H3 = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=11, spaceAfter=2,
                    textColor=colors.HexColor("#1F4E78"))
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9, leading=12,
                      spaceAfter=4)
SMALL = ParagraphStyle("Small", parent=styles["BodyText"], fontSize=8, leading=10,
                       textColor=colors.HexColor("#404040"))
TBL_CELL = ParagraphStyle("TblCell", parent=styles["BodyText"], fontSize=8, leading=10)
TBL_CELL_TINY = ParagraphStyle("TblCellTiny", parent=styles["BodyText"], fontSize=7,
                                leading=9)
TBL_HEAD = ParagraphStyle("TblHead", parent=styles["BodyText"], fontSize=8, leading=10,
                          textColor=colors.white, fontName="Helvetica-Bold")


def header_cell(text):
    return Paragraph(text, TBL_HEAD)


def cell(text):
    return Paragraph(text, TBL_CELL)


def tiny_cell(text):
    return Paragraph(text, TBL_CELL_TINY)


def perf_table(rows, highlight_indices=()):
    """Competitor table: Client | Distribution | Zones | Ad Size | Calls | Qual | Missed | QR | Email"""
    headers = ["Client", "Distribution", "Zones", "Ad Size", "Total Calls",
               "Qual", "Missed", "QR", "Email (Camp/Clicks)"]
    data = [[header_cell(h) for h in headers]]
    for r in rows:
        data.append([cell(c) for c in r])
    col_widths = [1.95*inch, 0.7*inch, 1.05*inch, 1.95*inch, 0.7*inch,
                  0.5*inch, 0.6*inch, 0.5*inch, 1.15*inch]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1F4E78")),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("ALIGN", (1,0), (-1,-1), "CENTER"),
        ("ALIGN", (0,0), (0,-1), "LEFT"),
        ("ALIGN", (3,0), (3,-1), "LEFT"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F4F6F9")]),
        ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#BFBFBF")),
        ("BOTTOMPADDING", (0,0), (-1,0), 6),
        ("TOPPADDING", (0,0), (-1,0), 6),
    ]
    for i in highlight_indices:
        style.append(("BACKGROUND", (0, i+1), (-1, i+1), colors.HexColor("#FFF2CC")))
        style.append(("FONTNAME", (0, i+1), (-1, i+1), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))
    return t


def footprint_table():
    rows = [
        ("Category", DUNRITE_FOOTPRINT["category"]),
        ("Market", DUNRITE_FOOTPRINT["market"]),
        ("Distribution per issue", DUNRITE_FOOTPRINT["distribution"]),
        ("Spend (12 mo)", DUNRITE_FOOTPRINT["spend_12mo"]),
        ("Spend (2026 YTD)", DUNRITE_FOOTPRINT["spend_ytd"]),
        ("Call tracking", DUNRITE_FOOTPRINT["call_tracking"]),
        ("Email engagement", DUNRITE_FOOTPRINT["email"]),
        ("Products in market", DUNRITE_FOOTPRINT["products"]),
    ]
    data = [[Paragraph(f"<b>{k}</b>", TBL_CELL), Paragraph(v, TBL_CELL)] for k, v in rows]
    t = Table(data, colWidths=[1.7*inch, 8.3*inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.HexColor("#F4F6F9"), colors.white]),
        ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#BFBFBF")),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    return t


def monthly_table():
    """Dun-Rite monthly campaign breakdown."""
    headers = ["Issue", "EPC", "ND", "NOCO", "SD", "Other", "Total Spend"]
    data = [[header_cell(h) for h in headers]]
    for r in DUNRITE_MONTHLY:
        data.append([tiny_cell(c) for c in r])
    col_widths = [1.0*inch, 1.6*inch, 2.1*inch, 1.45*inch, 2.4*inch, 0.95*inch, 0.85*inch]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1F4E78")),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (0,0), (-1,0), "CENTER"),
        ("ALIGN", (-1,1), (-1,-1), "RIGHT"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F4F6F9")]),
        ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#BFBFBF")),
        ("BOTTOMPADDING", (0,0), (-1,0), 6),
        ("TOPPADDING", (0,0), (-1,0), 6),
        ("LEFTPADDING", (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
        # Highlight the 2026 expansion months
        ("BACKGROUND", (0,9), (-1,11), colors.HexColor("#FFF2CC")),
        ("FONTNAME", (0,9), (-1,11), "Helvetica-Bold"),
    ]))
    return t


def keypoints_table():
    data = []
    for i, (left, right) in enumerate(KEY_POINTS):
        if i == 0:
            data.append([header_cell(left), header_cell(right)])
        else:
            data.append([Paragraph(f"<b>{left}</b>", TBL_CELL), Paragraph(right, TBL_CELL)])
    t = Table(data, colWidths=[1.8*inch, 8.2*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1F4E78")),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F4F6F9")]),
        ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#BFBFBF")),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    return t


def build():
    today = date.today()
    stamp = f"{today.month}-{today.day}-{today.year}"
    out_path = OUTPUT_DIR / f"[C] Dun-Rite Rep Prep {stamp}.pdf"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out_path), pagesize=landscape(letter),
        leftMargin=0.4*inch, rightMargin=0.4*inch,
        topMargin=0.4*inch, bottomMargin=0.4*inch,
        title="Dun-Rite Rep Prep", author="THM Media",
    )

    story = []

    # ---- Header ----
    story.append(Paragraph("Dun-Rite Kitchens &amp; Baths — Category Performance Comparables", H1))
    story.append(Paragraph(
        f"Prepared {today:%B %d, %Y} · Comparable CO client performance across Kitchen &amp; "
        f"Bath, Windows &amp; Doors, and Basement Finishing &amp; Remodeling. "
        f"Two views: rolling 12 months and 2026 YTD.",
        SMALL))
    story.append(Spacer(1, 10))

    # ---- Footprint ----
    story.append(Paragraph("Dun-Rite Current Footprint", H2))
    story.append(footprint_table())

    # ---- Monthly campaign breakdown ----
    story.append(PageBreak())
    story.append(Paragraph("Dun-Rite — Full Campaign Breakdown by Issue (Last 12 Months)", H2))
    story.append(Paragraph(
        "Every placement Dun-Rite ran in each issue, by zone. Highlighted rows mark the "
        "2026 expansion — January through March added Full Page, Double Page, OPP PopOut, "
        "and zone Exclusive/Sponsored positions on top of the steady 1/2 Page footprint.",
        BODY))
    story.append(Spacer(1, 4))
    story.append(monthly_table())

    # ---- Kitchen & Bath ----
    story.append(PageBreak())
    story.append(Paragraph("Kitchen &amp; Bath — Top CO Performers", H2))
    story.append(Paragraph(
        "<b>Closest direct comparable:</b> ReNew Home Innovations (highlighted) — same 380K "
        "CO distribution, same 4-zone footprint as Dun-Rite. Distribution column reflects "
        "households per issue; ad size shows the dominant placement and any premium "
        "positions running alongside.",
        BODY))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Last 12 Months", H3))
    story.append(perf_table(KB_12MO, highlight_indices=(0,)))
    story.append(Spacer(1, 12))

    story.append(Paragraph("2026 YTD (Jan 1 – Today)", H3))
    story.append(perf_table(KB_YTD, highlight_indices=(0,)))

    # ---- Windows & Doors ----
    story.append(PageBreak())
    story.append(Paragraph("Windows &amp; Doors — Top CO Performers", H2))
    story.append(Paragraph(
        "Filtered to clients with confirmed CallRail and true windows/doors installation "
        "lines. Adjacent categories — window wells (a basement product), window cleaning, "
        "blinds, outdoor living, decks, and the national Renewal by Andersen cross-market "
        "records — are excluded so the comparison stays apples-to-apples with Dun-Rite's "
        "Windows &amp; Doors offering.",
        BODY))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Last 12 Months", H3))
    story.append(perf_table(WD_12MO))
    story.append(Spacer(1, 12))

    story.append(Paragraph("2026 YTD (Jan 1 – Today)", H3))
    story.append(perf_table(WD_YTD))

    # ---- Basements ----
    story.append(PageBreak())
    story.append(Paragraph("Basement Finishing &amp; Remodeling — Top CO Performers", H2))
    story.append(Paragraph(
        "Small bucket — only two active CO clients in this category with meaningful spend.",
        BODY))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Last 12 Months", H3))
    story.append(perf_table(BASEMENT_12MO))
    story.append(Spacer(1, 12))

    story.append(Paragraph("2026 YTD (Jan 1 – Today)", H3))
    story.append(perf_table(BASEMENT_YTD))

    # ---- Key Points ----
    story.append(PageBreak())
    story.append(Paragraph("Key Points", H2))
    story.append(Paragraph(
        "Observations and category context drawn from the comparable performance data above.",
        BODY))
    story.append(Spacer(1, 6))
    story.append(keypoints_table())

    doc.build(story)
    return out_path


if __name__ == "__main__":
    p = build()
    print(f"Wrote: {p}")
