"""Build the Roofers (NoCO + CO-wide context) Category Performance PDF."""

from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

OUTPUT = Path(__file__).resolve().parent.parent / "output" / "[C] Roofers NoCO Category Performance - Full Rundown.pdf"
OUTPUT.parent.mkdir(exist_ok=True)

NAVY = HexColor("#1A3A5C")
ACCENT = HexColor("#D95D39")
GRAY = HexColor("#5C6370")
LIGHT = HexColor("#F2F4F7")
BORDER = HexColor("#D0D5DD")
CAUTION = HexColor("#FFF4E1")

styles = getSampleStyleSheet()
title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontName="Helvetica-Bold",
                              fontSize=18, textColor=NAVY, spaceAfter=4)
subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontName="Helvetica",
                                 fontSize=10, textColor=GRAY, spaceAfter=14)
h1_style = ParagraphStyle("H1", parent=styles["Heading2"], fontName="Helvetica-Bold",
                           fontSize=13, textColor=NAVY, spaceBefore=14, spaceAfter=6)
body_style = ParagraphStyle("Body", parent=styles["Normal"], fontName="Helvetica",
                             fontSize=10, textColor=black, leading=13, spaceAfter=6)
body_bold_style = ParagraphStyle("BodyBold", parent=body_style, fontName="Helvetica-Bold")
caution_style = ParagraphStyle("Caution", parent=body_style, backColor=CAUTION,
                                borderColor=ACCENT, borderWidth=0, borderPadding=6, leftIndent=0)
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
    story.append(Paragraph("Roofers — Northern Colorado", title_style))
    story.append(Paragraph(
        "THMedia | 12-month rundown: April 2025 – April 2026 | Primary focus: NoCO · Context from ND, SD, EPC",
        subtitle_style,
    ))

    # ===== CAVEAT =====
    caveat_tbl = Table([[Paragraph(
        "<b>Sample-size note:</b> Only 2 roofers are currently booked in NoCO (5 Star Roofing, Roof Rejuvenate) "
        "and only 3 had meaningful call volume in the last 12 months. This report presents NoCO honestly and "
        "includes Colorado-wide performance from other zones (ND, SD, EPC) to give the prospect a fuller picture "
        "of what the category can deliver.",
        body_style,
    )]], colWidths=[7.5 * inch])
    caveat_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CAUTION),
        ("BOX", (0, 0), (-1, -1), 1, ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(caveat_tbl)

    # ===== FOOTPRINT =====
    story.append(Paragraph("Category footprint", h1_style))
    story.append(Paragraph(
        "<b>5 roofers currently booked across Colorado — 2 in NoCO (40%).</b> "
        "Low saturation category with room for a new entrant.",
        body_style,
    ))

    footprint = [
        ["Client", "Zones", "Future Orders"],
        ["J &amp; K Roofing", "ND, SD", "26"],
        ["5 Star Roofing &amp; Home Improvement / Window Depot", "NoCO", "23"],
        ["THM National – Medallion Roofing", "ND, SD", "18"],
        ["Meyer Roofing", "EPC", "12"],
        ["Roof Rejuvenate of Colorado", "NoCO", "7"],
    ]
    wrapped = [footprint[0]]
    for row in footprint[1:]:
        wrapped.append([Paragraph(row[0], cell_style), row[1], row[2]])
    t = Table(wrapped, colWidths=[4.0 * inch, 2.0 * inch, 1.5 * inch])
    ts = table_style()
    # Highlight NoCO clients
    ts.add("BACKGROUND", (0, 2), (-1, 2), HexColor("#E8F4F8"))
    ts.add("BACKGROUND", (0, 5), (-1, 5), HexColor("#E8F4F8"))
    t.setStyle(ts)
    story.append(t)
    story.append(Paragraph(
        "<i>Shaded rows = currently running in NoCO.</i>",
        small_style,
    ))

    # ===== SEASONALITY =====
    story.append(Paragraph("Category seasonality", h1_style))
    story.append(Paragraph(
        "<b>Colorado-wide roofer calls (all zones):</b>",
        body_style,
    ))
    seasonality = [
        ["Month", "Calls", "Qualified"],
        ["Apr 2025", "27", "18"],
        ["May 2025", "28", "17"],
        ["Jun 2025", "49", "21"],
        ["Jul 2025", "35", "7"],
        ["Aug 2025", "35", "11"],
        ["Sep 2025", "34", "16"],
        ["Oct 2025", "26", "8"],
        ["Nov 2025", "20", "10"],
        ["Dec 2025", "5", "0"],
        ["Jan 2026", "12", "6"],
        ["Feb 2026", "16", "6"],
        ["Mar 2026", "36", "11"],
        ["Apr 2026 (MTD)", "11", "5"],
    ]
    t = Table(seasonality, colWidths=[2.2 * inch, 1.8 * inch, 1.8 * inch])
    ts = table_style()
    ts.add("BACKGROUND", (0, 3), (-1, 3), HexColor("#FFE8DC"))  # Jun 2025
    ts.add("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold")
    ts.add("BACKGROUND", (0, 6), (-1, 6), HexColor("#FFE8DC"))  # Sep 2025
    ts.add("FONTNAME", (0, 6), (-1, 6), "Helvetica-Bold")
    t.setStyle(ts)
    story.append(t)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "<b>NoCO-only totals:</b> 100 calls / 31 qualified over 12 months. Peak was August (18 calls). Same general shape as "
        "the CO-wide pattern.",
        body_style,
    ))
    story.append(Paragraph(
        "<b>The story:</b> Roofers peak in <b>June (post-storm season)</b> with a second bump in <b>Sep–Oct</b> when homeowners "
        "spot damage before winter. 124 qualified leads in April–September alone = <b>76% of the year's qualified volume</b>. "
        "A spring signup lands the prospect right before peak demand.",
        body_style,
    ))

    story.append(PageBreak())

    # ===== TOP PERFORMERS =====
    story.append(Paragraph("Top performers — Colorado (12 months)", h1_style))
    story.append(Paragraph(
        "Ranked by qualified calls. Includes roofers from every CO zone for full context. "
        "NoCO clients are shaded.",
        body_style,
    ))

    perf = [
        ["#", "Client", "Zones", "Calls", "Qual", "Qual %", "Missed", "Orders", "Main ad size"],
        ["1", "J &amp; K Roofing", "ND, SD", "191", "91", "47.6%", "25", "44", "Full Page + OPP PopOut"],
        ["2", "5 Star Roofing &amp; Home Improvement / Window Depot", "NoCO", "51", "20", "39.2%", "7", "27", "1/2 Page + NoCO Sponsored"],
        ["3", "Meyer Roofing", "EPC", "36", "13", "36.1%", "10", "17", "1/2 Page + EPC Sponsored"],
        ["4", "Efficient Exteriors &amp; Roofing", "NoCO", "18", "5", "27.8%", "0", "6", "1/2 Page"],
        ["5", "Roof Rejuvenate of Colorado", "NoCO", "24", "3", "12.5%", "10", "8", "Full Page + NoCO Sponsored"],
    ]
    wrapped = [perf[0]]
    for row in perf[1:]:
        wrapped.append([
            row[0],
            Paragraph(row[1], cell_style),
            Paragraph(row[2], cell_style),
            row[3], row[4], row[5], row[6], row[7],
            Paragraph(row[8], cell_style),
        ])
    t = Table(wrapped, colWidths=[0.3 * inch, 2.1 * inch, 0.8 * inch, 0.5 * inch, 0.5 * inch, 0.55 * inch, 0.55 * inch, 0.55 * inch, 1.75 * inch])
    ts = table_style()
    # Shade NoCO rows (2, 4, 5)
    for row_i in (2, 4, 5):
        ts.add("BACKGROUND", (0, row_i), (-1, row_i), HexColor("#E8F4F8"))
    t.setStyle(ts)
    story.append(t)
    story.append(Paragraph(
        "<i>Shaded rows = NoCO.</i>",
        small_style,
    ))

    # ===== QR + EMAIL =====
    story.append(Paragraph("QR scans + Email engagement (12mo)", h1_style))
    story.append(Paragraph(
        "<b>Email is the strongest signal in this category.</b> Average CTR across these campaigns is ~13–14%.",
        body_style,
    ))
    digital = [
        ["Client", "Zone(s)", "Campaigns", "Views", "Clicks"],
        ["5 Star Roofing (NoCO)", "NoCO", "8", "49,046", "7,016"],
        ["J &amp; K Roofing", "ND, SD", "7", "51,803", "6,993"],
        ["Meyer Roofing", "EPC", "3", "18,174", "2,532"],
        ["Roof Rejuvenate of Colorado", "NoCO", "2", "13,322", "1,711"],
    ]
    t = Table(digital, colWidths=[3.0 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch])
    ts = table_style()
    # Shade NoCO rows
    ts.add("BACKGROUND", (0, 1), (-1, 1), HexColor("#E8F4F8"))
    ts.add("BACKGROUND", (0, 4), (-1, 4), HexColor("#E8F4F8"))
    t.setStyle(ts)
    story.append(t)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "<b>5 Star's 7,016 email clicks from NoCO campaigns</b> is arguably the strongest single number in this rundown. "
        "Email out-performs print as a lead channel for roofers — bundled Inbox Advantage is the real pitch.",
        body_style,
    ))

    story.append(PageBreak())

    # ===== FLAGSHIP 1 — J&K =====
    story.append(Paragraph("Flagship #1 (for scale): J &amp; K Roofing — Denver (ND + SD)", h1_style))
    story.append(Paragraph(
        "Running Full Page + OPP PopOut in every issue across both Denver zones. This is the scale story — what's "
        "possible when a roofer fully commits to the channel.",
        body_style,
    ))
    jk = [
        ["Month", "Calls", "Qualified", "First-time", "Missed"],
        ["Apr 2025", "14", "9", "9", "1"],
        ["May 2025", "17", "12", "15", "1"],
        ["Jun 2025", "31", "16", "25", "1"],
        ["Jul 2025", "18", "5", "10", "4"],
        ["Aug 2025", "13", "7", "5", "0"],
        ["Sep 2025", "18", "7", "11", "4"],
        ["Oct 2025", "19", "6", "11", "2"],
        ["Nov 2025", "15", "9", "11", "4"],
        ["Dec 2025", "2", "0", "1", "0"],
        ["Jan 2026", "8", "3", "6", "2"],
        ["Feb 2026", "8", "2", "3", "3"],
        ["Mar 2026", "22", "10", "17", "3"],
        ["Apr 2026 (MTD)", "6", "5", "6", "0"],
        ["12-month total", "191", "91", "130", "25"],
    ]
    t = Table(jk, colWidths=[1.4 * inch, 1.0 * inch, 1.2 * inch, 1.6 * inch, 1.0 * inch])
    ts = table_style()
    ts.add("BACKGROUND", (0, 3), (-1, 3), HexColor("#FFE8DC"))  # Jun 2025 peak
    ts.add("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold")
    ts.add("BACKGROUND", (0, 12), (-1, 12), HexColor("#FFE8DC"))  # Mar 2026
    ts.add("FONTNAME", (0, 12), (-1, 12), "Helvetica-Bold")
    ts.add("BACKGROUND", (0, -1), (-1, -1), NAVY)
    ts.add("TEXTCOLOR", (0, -1), (-1, -1), white)
    ts.add("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")
    t.setStyle(ts)
    story.append(t)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "<b>Takeaway:</b> 91 qualified calls in 12 months — the category benchmark in Colorado. "
        "But <b>25 missed calls</b> (13% of volume) shows where the leak is. A roofer who actually picks up "
        "the phone could outperform J&amp;K.",
        body_style,
    ))

    # ===== FLAGSHIP 2 — 5 STAR =====
    story.append(Paragraph("Flagship #2 (NoCO specifically): 5 Star Roofing &amp; Home Improvement", h1_style))
    story.append(Paragraph(
        "NoCO zone · 1/2 Page + NoCO Sponsored slot · strongest on email engagement in the category.",
        body_style,
    ))
    fs = [
        ["Month", "Calls", "Qualified", "First-time", "Missed"],
        ["Apr 2025", "7", "5", "5", "0"],
        ["May 2025", "5", "2", "3", "0"],
        ["Jun 2025", "6", "2", "4", "0"],
        ["Jul 2025", "4", "0", "0", "1"],
        ["Aug 2025", "7", "2", "4", "1"],
        ["Sep 2025", "10", "6", "6", "2"],
        ["Oct 2025", "4", "2", "2", "0"],
        ["Nov 2025", "2", "1", "1", "0"],
        ["Dec 2025", "1", "0", "1", "0"],
        ["Jan 2026", "0", "0", "0", "0"],
        ["Feb 2026", "1", "0", "0", "1"],
        ["Mar 2026", "2", "0", "1", "1"],
        ["Apr 2026 (MTD)", "2", "0", "0", "1"],
        ["12-month total", "51", "20", "27", "7"],
    ]
    t = Table(fs, colWidths=[1.4 * inch, 1.0 * inch, 1.2 * inch, 1.6 * inch, 1.0 * inch])
    ts = table_style()
    ts.add("BACKGROUND", (0, 6), (-1, 6), HexColor("#FFE8DC"))  # Sep 2025 peak
    ts.add("FONTNAME", (0, 6), (-1, 6), "Helvetica-Bold")
    ts.add("BACKGROUND", (0, -1), (-1, -1), NAVY)
    ts.add("TEXTCOLOR", (0, -1), (-1, -1), white)
    ts.add("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")
    t.setStyle(ts)
    story.append(t)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "<b>Honest take:</b> Strong first half (18 qualified Apr–Sep), weaker second half (2 qualified Oct–Apr). "
        "The <b>email channel is where 5 Star wins</b> — 7,016 clicks from 8 campaigns, still booked through Nov 2026.",
        body_style,
    ))

    story.append(PageBreak())

    # ===== RECOMMENDATION =====
    story.append(Paragraph("Recommended starting package", h1_style))
    rec = [
        ["Tier", "Recommendation", "Why — based on the data"],
        ["Core (proven scale)", "Full Page + OPP PopOut",
         "J &amp; K Roofing's exact formula — 91 qualified calls in 12 months across Denver. The category benchmark."],
        ["NoCO-appropriate", "1/2 Page + NoCO Sponsored",
         "5 Star Roofing's model — right-sized for NoCO's smaller call volume. Pulled 20 qualified + 7,016 email clicks."],
        ["Zone add-on", "NoCO Sponsored / Premium slot",
         "5 Star layered 6+ Sponsored slots per year on top of their 1/2 Page. Boosts in-zone visibility."],
        ["Digital (strongest signal)", "Inbox Advantage email campaigns",
         "7,016 clicks/yr for 5 Star NoCO, 6,993 for J &amp; K. Email is the #1 lead driver in this category — ~4× industry CTR."],
        ["Operational priority", "Train on call pickup",
         "Top CO roofers missed 7–25 calls each in 12 months. The single most fixable leak — a roofer who picks up the phone can outperform incumbents."],
    ]
    wrapped = [rec[0]]
    for row in rec[1:]:
        wrapped.append([
            Paragraph(row[0], cell_style),
            Paragraph(row[1], body_bold_style),
            Paragraph(row[2], body_style),
        ])
    t = Table(wrapped, colWidths=[1.5 * inch, 2.0 * inch, 4.0 * inch])
    t.setStyle(table_style())
    story.append(t)

    # ===== PITCH ANGLES =====
    story.append(Paragraph("Pitch angles for the meeting", h1_style))
    for line in [
        "<b>\"Only 5 roofers currently booked across Colorado — 2 in NoCO.\"</b> Low saturation, clear lane for a new advertiser.",
        "<b>\"The category peaks June + September.\"</b> Post-storm season drives calls. A spring signup captures the full wave — 76% of the year's qualified leads hit between April and September.",
        "<b>\"Our top Colorado roofer pulled 91 qualified calls in 12 months.\"</b> J &amp; K Roofing in Denver is the scale story — Full Page + OPP PopOut is the replicable model.",
        "<b>\"Email out-performs print for roofers.\"</b> 5 Star got 7,016 clicks from 8 NoCO email campaigns. Inbox Advantage is the digital hook for this category.",
        "<b>\"The biggest leak is missed calls.\"</b> J &amp; K missed 25, Meyer 10, Roof Rejuvenate 10. A prospect who answers the phone can outperform the incumbents.",
    ]:
        story.append(Paragraph(f"• {line}", bullet_style))

    # ===== HONEST CAVEATS =====
    story.append(Paragraph("Honest caveats", h1_style))
    for line in [
        "NoCO roofer category is small and softening. The Colorado-wide story is meaningfully stronger — lean on J &amp; K for scale, 5 Star for NoCO-specific proof.",
        "5 Star's call volume trailed off after September — don't lean heavily on recent monthly numbers.",
        "J &amp; K is not a NoCO advertiser. They're the benchmark for what Colorado roofing in the Denver zones can deliver — use them as \"what's possible with the right commitment\" rather than a direct NoCO comparison.",
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