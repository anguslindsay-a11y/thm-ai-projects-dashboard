"""Build the Builders/Remodelers (CO) Category Performance PDF for a new-client meeting."""

from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

OUTPUT = Path(__file__).resolve().parent.parent / "output" / "[C] Builders-Remodelers CO Category Performance - Full Rundown.pdf"
OUTPUT.parent.mkdir(exist_ok=True)

NAVY = HexColor("#1A3A5C")
ACCENT = HexColor("#D95D39")
GRAY = HexColor("#5C6370")
LIGHT = HexColor("#F2F4F7")
BORDER = HexColor("#D0D5DD")

styles = getSampleStyleSheet()
title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontName="Helvetica-Bold",
                              fontSize=18, textColor=NAVY, spaceAfter=4)
subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontName="Helvetica",
                                 fontSize=10, textColor=GRAY, spaceAfter=16)
h1_style = ParagraphStyle("H1", parent=styles["Heading2"], fontName="Helvetica-Bold",
                           fontSize=13, textColor=NAVY, spaceBefore=14, spaceAfter=6)
body_style = ParagraphStyle("Body", parent=styles["Normal"], fontName="Helvetica",
                             fontSize=10, textColor=black, leading=13, spaceAfter=6)
body_bold_style = ParagraphStyle("BodyBold", parent=body_style, fontName="Helvetica-Bold")
small_style = ParagraphStyle("Small", parent=styles["Normal"], fontName="Helvetica-Oblique",
                              fontSize=8, textColor=GRAY, leading=10)
bullet_style = ParagraphStyle("Bullet", parent=body_style, leftIndent=14, bulletIndent=4)
cell_style = ParagraphStyle("Cell", parent=body_style, fontSize=8.5, leading=11, spaceAfter=0)


def table_style(header_bg=NAVY, header_fg=white, zebra=True):
    s = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), header_fg),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.25, BORDER),
    ]
    if zebra:
        s.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LIGHT]))
    return TableStyle(s)


def build():
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=letter,
        leftMargin=0.5 * inch, rightMargin=0.5 * inch,
        topMargin=0.5 * inch, bottomMargin=0.5 * inch,
    )
    story = []

    # ===== TITLE =====
    story.append(Paragraph("Builders &amp; Remodelers — Colorado", title_style))
    story.append(Paragraph(
        "THMedia | 12-month rundown: April 2025 – April 2026 | Zones: NOCO · ND · SD · EPC",
        subtitle_style,
    ))

    # ===== FOOTPRINT =====
    story.append(Paragraph("Category footprint", h1_style))
    story.append(Paragraph(
        "<b>22 currently booked CO Builders/Remodelers</b> — clients with at least one order dated today or in the future. "
        "Broad scope: Construction, Building &amp; Design, Home Remodeling, Basement Finishing, Home Improvement, and "
        "Kitchen &amp; Bath Remodeling. Home Improvement Express runs as one business across 4 zones (NOCO, ND, SD, EPC) "
        "with zone-routed CallRail tracking — shown separately below.",
        body_style,
    ))

    footprint = [
        ["Client", "Zones", "Future Orders"],
        ["ReNew Home Innovations", "EPC, ND, NOCO, SD", "81"],
        ["Dun-Rite Kitchens &amp; Baths", "EPC, ND, NOCO, SD", "70"],
        ["Home Improvement Express – EPC", "EPC", "29"],
        ["Home Improvement Express – NoCO", "NOCO", "29"],
        ["Stonebridge Builders", "ND, SD", "29"],
        ["Home Improvement Express – S Denver", "SD", "28"],
        ["Basement Finishers", "ND, SD", "27"],
        ["Home Improvement Express – N Denver", "ND", "27"],
        ["SimplySinks (Alpine Summit Industries)", "ND, SD", "27"],
        ["Build A Bath", "ND, SD", "24"],
        ["Wood Road Construction", "EPC", "22"],
        ["Planet Granite", "EPC, SD", "21"],
        ["ABD (Associates in Building + Design)", "NOCO", "19"],
        ["Best Construction Brands", "EPC", "18"],
        ["Dutch's Home Improvement", "EPC", "18"],
        ["Kitchen Tune Up – EPC", "EPC", "18"],
        ["THM National – Five Star Bath", "CO-wide", "18"],
        ["One Day Doors &amp; Closets", "EPC", "10"],
        ["MaK Construction", "SD", "6"],
        ["O'Keefe Built", "SD", "6"],
        ["A2Z Builders", "EPC, ND, SD", "4"],
        ["Sheffield Homes", "ND", "2"],
    ]
    wrapped = [footprint[0]]
    for row in footprint[1:]:
        wrapped.append([Paragraph(row[0], cell_style), row[1], row[2]])
    t = Table(wrapped, colWidths=[3.6 * inch, 2.2 * inch, 1.4 * inch])
    t.setStyle(table_style())
    story.append(t)

    # ===== SEASONALITY =====
    story.append(Paragraph("Category seasonality (CO)", h1_style))
    seasonality = [
        ["Month", "Calls", "Qualified", "Qual %"],
        ["Apr 2025", "165", "83", "50.3%"],
        ["May 2025", "158", "72", "45.6%"],
        ["Jun 2025", "153", "72", "47.1%"],
        ["Jul 2025", "218", "86", "39.4%"],
        ["Aug 2025", "199", "75", "37.7%"],
        ["Sep 2025", "214", "87", "40.7%"],
        ["Oct 2025", "227", "106", "46.7%"],
        ["Nov 2025", "155", "71", "45.8%"],
        ["Dec 2025", "120", "63", "52.5%"],
        ["Jan 2026", "206", "105", "51.0%"],
        ["Feb 2026", "145", "67", "46.2%"],
        ["Mar 2026", "201", "88", "43.8%"],
        ["Apr 2026 (MTD)", "52", "32", "61.5%"],
    ]
    t = Table(seasonality, colWidths=[1.8 * inch, 1.4 * inch, 1.4 * inch, 1.4 * inch])
    ts = table_style()
    for row_i in (7, 10):  # Oct 2025, Jan 2026 peaks
        ts.add("BACKGROUND", (0, row_i), (-1, row_i), HexColor("#FFE8DC"))
        ts.add("FONTNAME", (0, row_i), (-1, row_i), "Helvetica-Bold")
    t.setStyle(ts)
    story.append(t)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "<b>The story — and this is different from most categories:</b> Builders/Remodelers peak in "
        "<b>October and January</b>. Homeowners plan major projects after summer, research contractors "
        "during fall, and commit in the new year. October hit 227 calls / 106 qualified; January 2026 hit "
        "206 / 105. The opposite of HVAC's spring peak. A fall signup puts the prospect in the magazine "
        "at the front of the planning cycle.",
        body_style,
    ))

    story.append(PageBreak())

    # ===== TOP PERFORMERS =====
    story.append(Paragraph("Top performers — last 12 months", h1_style))
    story.append(Paragraph(
        "Ranked by qualified calls. \"Main ad size\" shows each client's primary print product over the "
        "last 12 months. Home Improvement Express is shown as 4 zone records because their CallRail tracking "
        "is split by zone — combined, HIE pulled <b>363 calls / 228 qualified</b>.",
        body_style,
    ))

    perf = [
        ["#", "Client", "Zones", "Calls", "Qual", "Qual %", "Orders", "Main ad size"],
        ["1", "ReNew Home Innovations", "EPC, ND, NOCO, SD", "270", "139", "51.5%", "81", "Full Page + Marketplace Listing"],
        ["2", "HIE – NoCO", "NOCO", "152", "111", "73.0%", "40", "1/2 Page + Marketplace + Zone Sponsored"],
        ["3", "Best Construction Brands", "EPC", "159", "101", "63.5%", "26", "Full Page + Marketplace Listing"],
        ["4", "Basement Finishers", "ND, SD", "143", "72", "50.3%", "39", "1/2 Page + Marketplace Listing"],
        ["5", "SimplySinks", "ND, SD", "99", "56", "56.6%", "22", "1/2 Page + Marketplace Listing"],
        ["6", "HIE – N Denver", "ND", "93", "52", "55.9%", "41", "1/2 Page + Marketplace + Zone Sponsored"],
        ["7", "A2Z Builders", "EPC, ND, SD", "94", "48", "51.1%", "57", "Full Page + Marketplace Listing"],
        ["8", "Kitchen Tune Up – EPC", "EPC", "78", "48", "61.5%", "27", "1/2 Page + Marketplace Listing"],
        ["9", "O'Keefe Built", "SD", "65", "43", "66.2%", "24", "Full Page + Marketplace Listing"],
        ["10", "Dutch's Home Improvement", "EPC", "65", "43", "66.2%", "26", "1/2 Page + Marketplace Listing"],
        ["11", "HIE – S Denver", "SD", "72", "40", "55.6%", "32", "1/2 Page + Marketplace + Zone Sponsored"],
        ["12", "Planet Granite", "EPC, SD", "121", "33", "27.3%", "29", "Full Page + Marketplace Listing"],
        ["13", "MaK Construction", "SD", "66", "29", "43.9%", "36", "Full Page + Marketplace + Double Page"],
        ["14", "Wood Road Construction", "EPC", "65", "28", "43.1%", "30", "Full Page + Marketplace + Double Page"],
        ["15", "HIE – EPC", "EPC", "46", "25", "54.3%", "22", "1/2 Page + Marketplace + Zone Sponsored"],
        ["16", "Build A Bath", "ND, SD", "73", "24", "32.9%", "38", "1/2 Page + Marketplace + Zone Sponsored"],
    ]
    # Wrap long cells
    wrapped = [perf[0]]
    for row in perf[1:]:
        wrapped.append([
            row[0],
            Paragraph(row[1], cell_style),
            Paragraph(row[2], cell_style),
            row[3], row[4], row[5], row[6],
            Paragraph(row[7], cell_style),
        ])
    t = Table(wrapped, colWidths=[0.3 * inch, 1.7 * inch, 1.15 * inch, 0.5 * inch, 0.5 * inch, 0.6 * inch, 0.55 * inch, 2.2 * inch])
    t.setStyle(table_style())
    story.append(t)

    # ===== QR + EMAIL =====
    story.append(Paragraph("QR scans + Email engagement (12mo)", h1_style))
    digital = [
        ["Client", "QR Scans", "Campaigns", "Views", "Clicks"],
        ["HIE – N Denver", "—", "16", "89,124", "12,079"],
        ["HIE – S Denver", "—", "11", "89,826", "11,923"],
        ["HIE – NoCO", "—", "14", "81,129", "10,913"],
        ["Dun-Rite Kitchens &amp; Baths", "—", "10", "63,314", "7,876"],
        ["MaK Construction", "28", "6", "62,577", "7,260"],
        ["Build A Bath", "20", "6", "46,866", "6,295"],
        ["Sheffield Homes", "—", "8", "39,419", "5,751"],
        ["HIE – EPC", "—", "7", "37,121", "5,269"],
        ["Wood Road Construction", "—", "4", "23,368", "3,473"],
        ["A2Z Builders", "—", "3", "23,193", "3,387"],
        ["Stonebridge Builders", "10", "4", "25,614", "3,244"],
        ["ReNew Home Innovations", "106", "—", "—", "—"],
        ["Best Baths", "47", "—", "—", "—"],
    ]
    t = Table(digital, colWidths=[2.8 * inch, 1.0 * inch, 1.2 * inch, 1.2 * inch, 1.3 * inch])
    t.setStyle(table_style())
    story.append(t)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "<b>Digital story:</b> Email CTR averages <b>13–14%</b> across these campaigns — roughly 4× industry benchmarks. "
        "Home Improvement Express's 4-zone email campaigns combined delivered <b>40,184 clicks</b> in 12 months.",
        body_style,
    ))

    story.append(PageBreak())

    # ===== FLAGSHIP DEEP DIVE =====
    story.append(Paragraph("Flagship monthly deep dive: ReNew Home Innovations", h1_style))
    story.append(Paragraph(
        "Kitchen &amp; Bath Remodeling · runs Full Page + Marketplace Listing in <b>every CO issue across all 4 zones</b> "
        "(EPC, ND, NOCO, SD) · 81 future orders booked through Dec 2026.",
        body_style,
    ))

    renew = [
        ["Month", "Calls", "Qualified", "First-time callers", "Missed"],
        ["Apr 2025", "19", "12", "12", "0"],
        ["May 2025", "12", "6", "6", "1"],
        ["Jun 2025", "17", "8", "8", "0"],
        ["Jul 2025", "19", "7", "13", "2"],
        ["Aug 2025", "17", "3", "8", "0"],
        ["Sep 2025", "14", "5", "6", "0"],
        ["Oct 2025", "29", "15", "14", "0"],
        ["Nov 2025", "38", "13", "19", "6"],
        ["Dec 2025", "18", "14", "12", "0"],
        ["Jan 2026", "39", "26", "28", "1"],
        ["Feb 2026", "24", "14", "17", "0"],
        ["Mar 2026", "24", "16", "15", "0"],
        ["12-month total", "270", "139", "158", "10"],
    ]
    t = Table(renew, colWidths=[1.4 * inch, 1.0 * inch, 1.2 * inch, 1.8 * inch, 1.0 * inch])
    ts = table_style()
    ts.add("BACKGROUND", (0, -1), (-1, -1), NAVY)
    ts.add("TEXTCOLOR", (0, -1), (-1, -1), white)
    ts.add("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")
    # Highlight the 2 biggest months
    ts.add("BACKGROUND", (0, 10), (-1, 10), HexColor("#FFE8DC"))  # Jan 2026
    ts.add("FONTNAME", (0, 10), (-1, 10), "Helvetica-Bold")
    t.setStyle(ts)
    story.append(t)

    story.append(Spacer(1, 10))
    story.append(Paragraph("Why ReNew anchors the pitch:", body_bold_style))
    for line in [
        "139 qualified leads in 12 months, ~58% first-time callers — new customer pipeline.",
        "Trending up hard in Q4 2025 + Q1 2026 — Jan 2026 was their best month ever (26 qualified calls).",
        "Running a Full Page in every single issue (92 full-page placements across 12 months, across 4 zones).",
        "Print-only on calls, QR-active (106 scans) — proves the physical magazine is doing the work.",
        "81 future orders booked through Dec 2026 — they've re-signed for another full year.",
    ]:
        story.append(Paragraph(f"• {line}", bullet_style))

    # ===== ALTERNATE FLAGSHIP =====
    story.append(Paragraph("Alternate flagship: Home Improvement Express (multi-zone)", h1_style))
    story.append(Paragraph(
        "If the prospect is a general remodeler / handyman hybrid rather than pure K&amp;B, HIE is the stronger story. "
        "One business running a zone-tailored ad in each of the 4 CO zones.",
        body_style,
    ))
    hie = [
        ["Zone", "Calls", "Qualified", "Qual %", "Orders 12mo", "Email Clicks"],
        ["NoCO", "152", "111", "73.0%", "40", "10,913"],
        ["N Denver", "93", "52", "55.9%", "41", "12,079"],
        ["S Denver", "72", "40", "55.6%", "32", "11,923"],
        ["EPC", "46", "25", "54.3%", "22", "5,269"],
        ["Combined", "363", "228", "62.8%", "135", "40,184"],
    ]
    t = Table(hie, colWidths=[1.3 * inch, 1.0 * inch, 1.2 * inch, 1.0 * inch, 1.3 * inch, 1.3 * inch])
    ts = table_style()
    ts.add("BACKGROUND", (0, -1), (-1, -1), NAVY)
    ts.add("TEXTCOLOR", (0, -1), (-1, -1), white)
    ts.add("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")
    t.setStyle(ts)
    story.append(t)

    # ===== RECOMMENDATION =====
    story.append(Paragraph("Recommended starting package", h1_style))
    story.append(Paragraph(
        "Based on what the top performers are running. Exact sizing depends on the prospect's budget and which zones they target.",
        body_style,
    ))

    rec = [
        ["Tier", "Recommendation", "Why — based on the data"],
        ["Core (preferred)", "Full Page + Marketplace Listing",
         "ReNew, Best Construction, A2Z, O'Keefe, MaK, Planet Granite, Wood Road all run this combo. ReNew runs it in every CO issue across all 4 zones and pulled 139 qualified leads."],
        ["Budget alternative", "1/2 Page + Marketplace Listing",
         "Dun-Rite, HIE (every zone), Basement Finishers, Kitchen Tune Up, Dutch's, Build A Bath. Still pulling 40–111 qualified/year."],
        ["Zone-targeted add-on", "Zone Sponsored slot",
         "HIE and Build A Bath add zone-specific Sponsored spots on top of their main ad. Drives zone-local awareness when the prospect focuses on one metro."],
        ["Heavy-volume add-on", "Double Page Spread (occasional)",
         "MaK, Wood Road, Dun-Rite, A2Z all run these occasionally. Strong brand statement when launching or seasonal push."],
        ["Digital add-on (strong recommend)", "Inbox Advantage email campaigns",
         "HIE's multi-zone email campaigns pulled 40,184 clicks in 12 months. B/R clients average 13–14% CTR — ~4× industry benchmark."],
        ["Multi-zone strategy", "Zone-tailored ads + CallRail per zone",
         "ReNew (4 zones) and HIE (4 zones as separate records) both prove the multi-zone model. Zone-specific tracking lets the prospect see which zone delivers best ROI."],
    ]
    wrapped = [rec[0]]
    for row in rec[1:]:
        wrapped.append([
            Paragraph(row[0], cell_style),
            Paragraph(row[1], body_bold_style),
            Paragraph(row[2], body_style),
        ])
    t = Table(wrapped, colWidths=[1.4 * inch, 2.1 * inch, 4.0 * inch])
    t.setStyle(table_style())
    story.append(t)

    # ===== PITCH ANGLES =====
    story.append(Paragraph("Pitch angles for the meeting", h1_style))
    for line in [
        "<b>\"22 Builders/Remodelers are currently booked — and they stick.\"</b> Average 27 future orders per client = 2+ years of forward bookings. Category loyalty is high.",
        "<b>\"Our category peaks Oct–Jan.\"</b> Homeowners research remodelers during fall and book in the new year. A fall signup lands the prospect at the front of that cycle.",
        "<b>\"Our top K&amp;B remodeler runs a Full Page in every issue, across all 4 zones, and hit 26 qualified leads in Jan 2026 alone.\"</b> ReNew's trajectory is the proof.",
        "<b>\"One of our remodelers pulled 40,000+ email clicks across 4 zones last year.\"</b> HIE's Inbox Advantage campaign is the digital story.",
        "<b>\"Qualification rates hit 50–73% for remodelers who answer the phone.\"</b> Missed calls hurt the category — clients who pick up (A2Z: 0 missed, SimplySinks: 1 missed) see the best results.",
    ]:
        story.append(Paragraph(f"• {line}", bullet_style))

    # ===== FOOTER =====
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Source: THMedia data warehouse, Apr 1, 2025 – Apr 8, 2026. Qualification uses the smart rule "
        "(excludes voicemails, spam, internal, wrong-number flags — not just 60s+ duration). "
        "Zones: NOCO (Northern Colorado), ND (North Denver), SD (South Denver), EPC (El Paso County).",
        small_style,
    ))

    doc.build(story)
    print(f"Saved: {OUTPUT}")


if __name__ == "__main__":
    build()