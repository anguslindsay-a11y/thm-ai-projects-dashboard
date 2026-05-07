"""Build the Decks & Porches UT Category Performance client-facing PDF."""

from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
)

OUTPUT = Path(__file__).resolve().parent.parent / "output" / "[C] Decks & Porches UT - Category Performance.pdf"
OUTPUT.parent.mkdir(exist_ok=True)

NAVY = HexColor("#1A3A5C")
ACCENT = HexColor("#D95D39")
GREEN = HexColor("#2E7D55")
GRAY = HexColor("#5C6370")
LIGHT = HexColor("#F2F4F7")
BORDER = HexColor("#D0D5DD")

styles = getSampleStyleSheet()
title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontName="Helvetica-Bold",
                              fontSize=18, textColor=NAVY, spaceAfter=1)
subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontName="Helvetica",
                                 fontSize=9, textColor=GRAY, spaceAfter=10)
h1_style = ParagraphStyle("H1", parent=styles["Heading2"], fontName="Helvetica-Bold",
                           fontSize=11, textColor=NAVY, spaceBefore=10, spaceAfter=4)
body_style = ParagraphStyle("Body", parent=styles["Normal"], fontName="Helvetica",
                             fontSize=9, textColor=black, leading=11.8, spaceAfter=3)
body_bold_style = ParagraphStyle("BodyBold", parent=body_style, fontName="Helvetica-Bold")
small_style = ParagraphStyle("Small", parent=styles["Normal"], fontName="Helvetica-Oblique",
                              fontSize=8, textColor=GRAY, leading=10)
cell_style = ParagraphStyle("Cell", parent=body_style, fontSize=9, leading=11, spaceAfter=0)
cell_bold = ParagraphStyle("CellB", parent=cell_style, fontName="Helvetica-Bold")


def ts(header_bg=NAVY, header_fg=white):
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), header_fg),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.25, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LIGHT]),
    ])


def build():
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=letter,
                             leftMargin=0.5*inch, rightMargin=0.5*inch,
                             topMargin=0.4*inch, bottomMargin=0.4*inch)
    story = []

    # ---- Header ----
    story.append(Paragraph("Decks &amp; Porches — Utah Category Performance", title_style))
    story.append(Paragraph("The Home Magazine Utah | 12-month snapshot | April 2025 – April 2026", subtitle_style))

    # ---- Category overview ----
    story.append(Paragraph("Category Overview", h1_style))
    overview_data = [
        ["22", "4,400+", "525+", "257"],
        ["Deck &amp; porch\nclients run", "Print ads placed\nacross UT zones", "Calls tracked\nvia CallRail", "Qualified leads\n(smart rules)"],
    ]
    overview_tbl = Table([
        [Paragraph(f"<font size=15 color='#1A3A5C'><b>{a}</b></font>", cell_style) for a in overview_data[0]],
        [Paragraph(f"<font size=8 color='#5C6370'>{a}</font>", cell_style) for a in overview_data[1]],
    ], colWidths=[1.85*inch]*4, rowHeights=[0.38*inch, 0.38*inch])
    overview_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER),
    ]))
    story.append(overview_tbl)

    # ---- Top performers ----
    story.append(Paragraph("Top 5 Performers — Last 12 Months", h1_style))
    story.append(Paragraph(
        "Ranked by qualified call volume. All clients run in multiple Utah zones (North / Central / South Wasatch). "
        "Full Page = 1-page print ad, 1/2 Page = half-page print ad.",
        small_style))
    story.append(Spacer(1, 4))

    top5 = [
        ["Client", "Status", "Tenure", "Ad Package", "Calls", "Qualified", "QR / Email"],
        ["Blackrock Decks", "Active", "27 mo",
         "Full Page\nin all 3 UT zones", "242", "107", "158 QR scans"],
        ["Boyd's Custom Patios", "Active", "25 mo",
         "Full Page\nin all 3 UT zones", "115", "67", "—"],
        ["McMorris Decks &amp; Structures", "Recently\nexpired", "23 mo",
         "1/2 Page + Sponsored\n(Central Wasatch)", "63", "39", "50 QR scans\n6,350 email clicks"],
        ["Legendary Decks", "Active", "12 mo",
         "1/2 Page + Marketplace\n(South Wasatch)", "50", "28", "—"],
        ["Redmond Valleywide", "Active", "25 mo",
         "Full Page\nin all 3 UT zones", "—", "—", "Own tracking\n(no CallRail)"],
    ]
    top5_rows = [top5[0]]  # plain strings for header so TableStyle white applies
    top5_rows += [[Paragraph(c, cell_style) for c in row] for row in top5[1:]]
    top5_tbl = Table(top5_rows,
                     colWidths=[1.4*inch, 0.7*inch, 0.55*inch, 1.55*inch, 0.5*inch, 0.7*inch, 1.3*inch])
    top5_tbl.setStyle(ts(NAVY, white))
    story.append(top5_tbl)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "<b>Why this matters:</b> Blackrock Decks and Boyd's Custom Patios both run Full Page ads in every Utah zone and have been in-book for 2+ years — this is the package that produces the highest, most consistent call volume. McMorris ran a more targeted Central Wasatch package and still generated 39 qualified leads plus strong digital engagement through Inbox Advantage email. Redmond Valleywide is a major multi-category spender who routes leads to their own phone lines (tracking not available through us).",
        body_style))

    # ---- Seasonality ----
    story.append(Paragraph("Seasonality — When Deck Leads Come In", h1_style))

    season_data = [
        ["Month", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"],
        ["Calls", "26", "87", "96", "59", "55", "25", "44", "15", "7", "14", "40", "51"],
        ["Qualified", "9", "58", "52", "32", "17", "12", "24", "3", "3", "2", "14", "22"],
    ]
    season_tbl = Table(season_data, colWidths=[0.7*inch] + [0.525*inch]*12,
                        rowHeights=[0.28*inch]*3)
    season_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.25, BORDER),
        # highlight peak season May–Jul
        ("BACKGROUND", (2, 1), (4, 2), HexColor("#E8F4EC")),
        ("BACKGROUND", (2, 0), (4, 0), GREEN),
    ]))
    story.append(season_tbl)
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "<b>Peak season:</b> May – July (homeowners planning outdoor projects). "
        "<b>Valley:</b> November – January. Leads rebound quickly in February as spring planning begins. "
        "Clients running continuously year-round capture both the peak rush and the planning-phase leads — "
        "prospects often call in winter to book a summer build.",
        body_style))

    # ---- Takeaways ----
    story.append(Paragraph("What This Tells Us", h1_style))
    takeaways = [
        "<b>The magazine works for Decks &amp; Porches in Utah.</b> 525+ tracked calls and 257 qualified leads across the category in 12 months — this is a proven category, not an experiment.",
        "<b>Full Page across all 3 zones is the winning package.</b> Our top 3 active performers all run this exact setup. It's what gets the phone ringing consistently from May through October.",
        "<b>Digital amplifies print.</b> Blackrock's QR code generated 158 scans on top of 242 calls. McMorris' 6 Inbox Advantage email drops delivered 44,900 views and 6,350 clicks — another way to stay top-of-mind between issues.",
        "<b>Year-round presence captures year-round intent.</b> Pausing in winter means missing the February – March surge when spring projects get planned.",
    ]
    for t in takeaways:
        story.append(Paragraph("• " + t, body_style))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Data sources: CallRail (smart qualification — 60s+ excluding junk/internal), Magazine Manager order history, Uniqode QR tracking, Inbox Advantage email analytics. April 2025 – April 2026.",
        small_style))

    doc.build(story)
    print(f"Built: {OUTPUT}")


if __name__ == "__main__":
    build()
