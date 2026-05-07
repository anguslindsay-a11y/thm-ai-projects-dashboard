"""CO zone underperformers — design book flip review sheet."""

from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

OUTPUT = Path(__file__).resolve().parent.parent / "output" / "[C] CO Underperformers - Design Book Flip.pdf"
OUTPUT.parent.mkdir(exist_ok=True)

NAVY = HexColor("#1A3A5C")
RED = HexColor("#C0392B")
GRAY = HexColor("#5C6370")
LIGHT = HexColor("#F2F4F7")
BORDER = HexColor("#D0D5DD")

styles = getSampleStyleSheet()
title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontName="Helvetica-Bold",
                              fontSize=16, textColor=NAVY, spaceAfter=1)
subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontName="Helvetica",
                                 fontSize=8.5, textColor=GRAY, spaceAfter=8)
h1_style = ParagraphStyle("H1", parent=styles["Heading2"], fontName="Helvetica-Bold",
                           fontSize=11, textColor=NAVY, spaceBefore=8, spaceAfter=3)
body_style = ParagraphStyle("Body", parent=styles["Normal"], fontName="Helvetica",
                             fontSize=8.5, textColor=black, leading=11, spaceAfter=2)
small_style = ParagraphStyle("Small", parent=styles["Normal"], fontName="Helvetica-Oblique",
                              fontSize=7.5, textColor=GRAY, leading=9.5)
cell_style = ParagraphStyle("Cell", parent=body_style, fontSize=8.5, leading=10.5, spaceAfter=0)

DATA = {
    "NOCO — Northern Colorado": [
        ["Meglen's Waterwise Landscapes", "Full Page + DirSpot", 13, 23155, 1, 0, 0],
        ["KGuard Leaf Free Gutter System", "Front Cover + Full Page", 13, 19060, 0, 0, 0],
        ["Design Decking & Pergolas", "Full Page", 6, 11860, 0, 0, 0],
        ["L & B Concrete Borders", "Front Cover + Full Page", 5, 11480, 0, 0, 0],
        ["Advanced Curb Design / LIT Lighting", "Front Cover + Full Page", 4, 7538, 2, 0, 1],
    ],
    "ND — North Denver": [
        ["L & B Concrete Borders", "Front Cover + Full Page", 12, 28270, 0, 0, 0],
        ["Mountainland Covers", "1/4 + 1/2 + Full Page", 15, 26787, 0, 0, 0],
        ["Sheffield Homes", "1/2 + Full + Exclusive + Sponsored", 18, 23730, 10, 1, 7],
        ["KGuard Leaf Free Gutter System", "Full Page", 12, 17400, 0, 0, 0],
        ["Garden Art Landscaping", "Front Cover + Full Page", 7, 15576, 5, 1, 0],
    ],
    "SD — South Denver": [
        ["Elite Landscape and Outdoor Living", "Front Cover + Full Page", 15, 40214, 2, 0, 0],
        ["L & B Concrete Borders", "Front Cover + Full Page", 12, 36939, 0, 0, 0],
        ["Mountainland Covers", "1/4 + 1/2 + Full Page", 15, 33255, 0, 0, 0],
        ["KGuard Leaf Free Gutter System", "Front Cover + Full Page", 13, 26330, 0, 0, 0],
        ["SealWize Denver West", "1/4 Page", 13, 7800, 0, 0, 0],
    ],
    "EPC — El Paso County": [
        ["Around the House / Sunesta", "Double Page + Front Cover + Full Page", 16, 29951, 0, 0, 0],
        ["Home Storage Remedies", "1/4 + 1/2 Page", 17, 20415, 0, 0, 0],
        ["Grout Doctor - EPC", "1/2 Page", 17, 18700, 0, 0, 0],
        ["Gutter Helmet - EPC", "Full Page", 15, 17940, 1, 0, 0],
        ["CO Concrete LLC", "1/4 + 1/2 Page", 9, 5559, 1, 0, 1],
    ],
}


def ts():
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("GRID", (0, 0), (-1, -1), 0.25, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LIGHT]),
    ])


def build():
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=letter,
                             leftMargin=0.4*inch, rightMargin=0.4*inch,
                             topMargin=0.35*inch, bottomMargin=0.35*inch)
    story = []

    story.append(Paragraph("Colorado Underperformers — Design Book Flip", title_style))
    story.append(Paragraph(
        "Active clients, 3+ orders in last 12 months, ranked by fewest qualified calls. April 2025 – April 2026.",
        subtitle_style))

    for zone_name, rows in DATA.items():
        story.append(Paragraph(zone_name, h1_style))
        headers = ["Client", "Ad Product", "Orders", "Spend", "Total Calls", "Qualified", "Missed"]
        table_rows = [headers]
        for r in rows:
            table_rows.append([
                Paragraph(r[0], cell_style),
                Paragraph(r[1], cell_style),
                str(r[2]),
                f"${r[3]:,}",
                str(r[4]),
                str(r[5]),
                str(r[6]),
            ])
        tbl = Table(table_rows, colWidths=[2.05*inch, 2.25*inch, 0.55*inch, 0.8*inch, 0.7*inch, 0.7*inch, 0.6*inch])
        tbl.setStyle(ts())
        story.append(tbl)

    story.append(Spacer(1, 8))
    story.append(Paragraph("Analysis", h1_style))
    bullets = [
        "<b>Creative refresh is the common thread.</b> Most of these clients run premium placements (Full Page, Front Cover) with zero qualified calls — the placement isn't the problem, the creative is.",
        "<b>Repeat offenders across zones:</b> L &amp; B Concrete Borders, KGuard Leaf Free Gutter, and Mountainland Covers all show up in 3–4 zones with near-zero calls. Category-wide rebuild candidates.",
        "<b>High-spend, near-zero return:</b> Elite Landscape (SD, $40k / 2 calls), Around the House Sunesta (EPC, $30k / 0 calls), and L &amp; B Concrete Borders (SD, $37k / 0 calls) are the most urgent retention risks.",
        "<b>Sheffield Homes (ND):</b> 18 orders across 4 ad products including Sponsored/Exclusive positions but 7 missed calls — this one may be a phone-answering issue, not creative.",
    ]
    for b in bullets:
        story.append(Paragraph("• " + b, body_style))

    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Note: Call data is from CallRail at the account level (not always zone-attributed). Clients with calls across multiple zones show the aggregate.",
        small_style))

    doc.build(story)
    print(f"Built: {OUTPUT}")


if __name__ == "__main__":
    build()
