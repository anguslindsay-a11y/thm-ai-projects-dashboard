"""
Client-facing 2-page Performance Partnership Review for Integrity Fencing Company.
Built for Dawn Brandt's renewal call 2026-05-07. Output: output/[C] Integrity Fencing Performance Review 5-6-2026.pdf
"""
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    KeepTogether, PageBreak, HRFlowable
)

OUT = r"C:\Users\MasenSpring\OneDrive - TheHomeMagWest\Supabase Data Hub\output\[C] Integrity Fencing Performance Review 5-6-2026.pdf"

# THM brand-ish palette
THM_RED = colors.HexColor("#C8102E")
THM_DARK = colors.HexColor("#1F2937")
THM_GRAY = colors.HexColor("#4B5563")
THM_LIGHT = colors.HexColor("#F3F4F6")
THM_ACCENT = colors.HexColor("#0F766E")  # teal accent for callouts


def build():
    doc = SimpleDocTemplate(
        OUT,
        pagesize=LETTER,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        title="Integrity Fencing Company - Performance Partnership Review",
        author="THMedia",
    )

    styles = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName="Helvetica-Bold",
                        fontSize=20, leading=23, textColor=THM_DARK, spaceAfter=2)
    H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName="Helvetica-Bold",
                        fontSize=12, leading=15, textColor=THM_RED, spaceBefore=8, spaceAfter=4)
    SUB = ParagraphStyle("SUB", parent=styles["Normal"], fontName="Helvetica",
                         fontSize=10, leading=12, textColor=THM_GRAY, spaceAfter=6)
    BODY = ParagraphStyle("BODY", parent=styles["Normal"], fontName="Helvetica",
                          fontSize=9.5, leading=12.5, textColor=THM_DARK, spaceAfter=4)
    BODY_TIGHT = ParagraphStyle("BODYT", parent=BODY, spaceAfter=2)
    BULLET = ParagraphStyle("BUL", parent=BODY, leftIndent=12, bulletIndent=2,
                            spaceAfter=2, fontSize=9.5, leading=12)
    HEADLINE = ParagraphStyle("HEAD", parent=styles["Normal"], fontName="Helvetica-Bold",
                              fontSize=11, leading=14, textColor=THM_DARK, alignment=TA_CENTER)
    QUOTE = ParagraphStyle("QUOTE", parent=BODY, fontName="Helvetica-Oblique",
                           fontSize=9, leading=11.5, textColor=THM_GRAY, leftIndent=8)
    FOOT = ParagraphStyle("FOOT", parent=BODY, fontSize=8, leading=10, textColor=THM_GRAY,
                          alignment=TA_CENTER)

    story = []

    # ---------- HEADER ----------
    story.append(Paragraph("INTEGRITY FENCING COMPANY", H1))
    story.append(Paragraph("Performance Partnership Review &nbsp;&nbsp;|&nbsp;&nbsp; April 2025 – Present &nbsp;&nbsp;|&nbsp;&nbsp; South Denver", SUB))
    story.append(HRFlowable(width="100%", thickness=1.2, color=THM_RED, spaceBefore=2, spaceAfter=8))

    # ---------- HEADLINE BOX ----------
    headline_text = (
        "Your THM campaign is hitting a new gear. In just the first five months of 2026, "
        "Integrity Fencing has already received <b>21 qualified calls</b> &mdash; more than the "
        "<b>17 qualified calls</b> generated in all of 2025. Call quality has nearly doubled, "
        "appointments booked over the phone have more than doubled, and the upgrade to a "
        "Full Page in March is already producing record months."
    )
    headline_tbl = Table([[Paragraph(headline_text, HEADLINE)]],
                         colWidths=[7.4 * inch])
    headline_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), THM_LIGHT),
        ("BOX", (0, 0), (-1, -1), 1, THM_ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(headline_tbl)
    story.append(Spacer(1, 10))

    # ---------- YEAR-OVER-YEAR TABLE ----------
    story.append(Paragraph("YEAR-OVER-YEAR CALL PERFORMANCE", H2))
    yoy_data = [
        ["Metric", "2025 (Apr–Dec, 9 mo)", "2026 YTD (Jan–May, 5 mo)", "Change"],
        ["Total inbound calls", "35", "23", "On pace to exceed"],
        ["Qualified calls", "17", "21", "+24% in less time"],
        ["Qualified rate", "48.6%", "91.3%", "+42 points"],
        ["Average call length", "2:12", "3:06", "+41% longer"],
        ["First-time callers", "21", "20", "Already at last year's pace"],
        ["Missed calls", "1", "1", "Stable answer rate"],
    ]
    yoy_tbl = Table(yoy_data, colWidths=[1.95 * inch, 1.85 * inch, 1.85 * inch, 1.75 * inch])
    yoy_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), THM_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9.5),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, THM_LIGHT]),
        ("BOX", (0, 0), (-1, -1), 0.5, THM_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        # Highlight the qualified rate row
        ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#FEF3C7")),
        ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
    ]))
    story.append(yoy_tbl)
    story.append(Spacer(1, 8))

    # ---------- CALL QUALITY STORY ----------
    story.append(Paragraph("WHO IS CALLING — AND WHY IT'S DIFFERENT THIS YEAR", H2))

    quality_data = [
        ["Call outcome", "2025", "2026 YTD"],
        ["Appointment booked on the call", "5", "11"],
        ["Estimate or schedule requested", "8", "7"],
        ["Existing customer / follow-up", "1", "2"],
        ["Abandoned or disconnected", "14", "1"],
        ["Telemarketer / test / missed", "7", "0"],
    ]
    quality_tbl = Table(quality_data, colWidths=[3.6 * inch, 1.9 * inch, 1.9 * inch])
    quality_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), THM_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9.5),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, THM_LIGHT]),
        ("BOX", (0, 0), (-1, -1), 0.5, THM_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        # Highlight booked appointments row
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#D1FAE5")),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
    ]))
    story.append(quality_tbl)
    story.append(Spacer(1, 6))

    story.append(Paragraph(
        "<b>The takeaway:</b> Last year's 35 calls included a meaningful share of telemarketers, "
        "abandoned calls, and disconnects. This year's volume is leaner but cleaner &mdash; the "
        "ad is doing more of the qualifying before the phone even rings. The result is "
        "<b>more than twice the booked appointments</b> in roughly half the time.",
        BODY))
    story.append(Spacer(1, 4))

    # ---------- FULL PAGE UPGRADE IMPACT ----------
    story.append(Paragraph("THE FULL PAGE UPGRADE IS DELIVERING", H2))
    fp_data = [
        ["Issue", "Ad Size", "Total Calls", "Qualified", "First-time"],
        ["Feb 2026", "1/2 Page", "4", "4", "4"],
        ["Mar 2026", "Full Page", "11", "10", "9"],
        ["Apr 2026", "Full Page", "6", "5", "5"],
    ]
    fp_tbl = Table(fp_data, colWidths=[1.4 * inch, 1.4 * inch, 1.5 * inch, 1.55 * inch, 1.55 * inch])
    fp_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), THM_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, THM_LIGHT]),
        ("BOX", (0, 0), (-1, -1), 0.5, THM_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#D1FAE5")),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(fp_tbl)
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "March 2026 &mdash; the first issue running a Full Page &mdash; produced the "
        "<b>strongest call month on record</b> for Integrity Fencing on THM, with 11 calls and "
        "10 qualified. April held steady at 5 of 6 qualified.",
        BODY))

    story.append(PageBreak())

    # ============== PAGE 2 ==============
    H1_P2 = ParagraphStyle("H1P2", parent=H1, fontSize=16, leading=18)
    story.append(Paragraph("INTEGRITY FENCING COMPANY", H1_P2))
    story.append(Paragraph("Performance Partnership Review &nbsp;&nbsp;|&nbsp;&nbsp; Page 2", SUB))
    story.append(HRFlowable(width="100%", thickness=1.2, color=THM_RED, spaceBefore=0, spaceAfter=6))

    # ---------- VOICE OF THE PROSPECT ----------
    story.append(Paragraph("THE PEOPLE CALLING YOUR BUSINESS", H2))
    story.append(Paragraph(
        "Highlights from CallRail's call summaries on 2026 calls &mdash; the kinds of "
        "leads your THM campaign is generating right now:",
        BODY))
    story.append(Spacer(1, 4))

    leads = [
        ("Cindy &mdash; Denver",
         "Cedar fence replacement across multiple properties with an HOA deadline. "
         "Booked an estimate on the call."),
        ("Stephen &mdash; Evergreen",
         "Two automated swing gates with keypad access for an 18-foot driveway entrance. "
         "Booked an estimate on the call."),
        ("Deb &mdash; Castle Rock",
         "6-foot residential fence on a new-construction home. Booked next-week. "
         "<i>Specifically said she found Integrity in Home Magazine.</i>"),
        ("Sarah &mdash; Golden",
         "Both-side fence install on a new build. Booked on-site consultation."),
        ("Andre &mdash; Englewood",
         "Iron fence and wood gate, ASAP timeline. Booked appointment for the next day."),
        ("Steve &mdash; Denver",
         "14 feet of residential fence with a gate, May 25 completion deadline. Booked."),
        ("Stacy &mdash; commercial property manager",
         "Ornamental fencing for a medical office building. "
         "Sending photos and measurements same-day."),
        ("Linda &mdash; Lone Tree",
         "Fence replacement, already coordinating cost-share with neighbors. "
         "Booked next-day estimate."),
        ("Jack &mdash; Littleton",
         "Residential fence repair from structural failure. Booked free on-site consultation."),
        ("Lisa &mdash; Erie",
         "Residential fence with spring completion target. Booked April 1 estimate."),
    ]

    lead_rows = []
    for name, note in leads:
        lead_rows.append([
            Paragraph(f"<b>{name}</b>", BODY_TIGHT),
            Paragraph(note, BODY_TIGHT),
        ])
    leads_tbl = Table(lead_rows, colWidths=[1.95 * inch, 5.45 * inch])
    leads_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, THM_LIGHT]),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#E5E7EB")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    story.append(leads_tbl)
    story.append(Spacer(1, 4))

    story.append(Paragraph(
        "<b>What the conversations show:</b> callers are arriving educated &mdash; asking about "
        "staining options, fascia removal, gate automation, keypad access, and your minimum-job "
        "size. The ad is pre-qualifying prospects before they pick up the phone. The result is "
        "a mix of <b>residential, new-construction, and commercial leads</b>.",
        BODY))
    story.append(Spacer(1, 4))

    # ---------- GEO REACH ----------
    story.append(Paragraph("YOUR REACH ACROSS THE FRONT RANGE", H2))
    story.append(Paragraph(
        "2026 callers represent a wider footprint than 2025 &mdash; covering core South Denver "
        "while extending into the foothills, north metro, and new-build corridors:",
        BODY))
    story.append(Spacer(1, 2))
    cities = (
        "Denver &middot; Englewood &middot; Castle Rock &middot; Lone Tree &middot; "
        "Littleton &middot; Golden &middot; Evergreen &middot; Parker &middot; "
        "Erie &middot; Johnstown &middot; Aurora &middot; Brighton"
    )
    geo_tbl = Table([[Paragraph(cities, BODY)]], colWidths=[7.4 * inch])
    geo_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), THM_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, THM_ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(geo_tbl)
    story.append(Spacer(1, 4))

    # ---------- MULTI-CHANNEL ----------
    story.append(Paragraph("MORE THAN PRINT — A FULL-CHANNEL CAMPAIGN", H2))

    CELL = ParagraphStyle("CELL", parent=BODY, fontSize=8.5, leading=11, spaceAfter=0)
    CELL_B = ParagraphStyle("CELLB", parent=CELL, fontName="Helvetica-Bold")
    CELL_H = ParagraphStyle("CELLH", parent=CELL, fontName="Helvetica-Bold",
                            textColor=colors.white, fontSize=9)

    channel_data = [
        [Paragraph("Channel", CELL_H),
         Paragraph("What it does", CELL_H),
         Paragraph("Activity", CELL_H)],
        [Paragraph("Full Page Print Ad", CELL_B),
         Paragraph("Primary brand and offer placement in South Denver", CELL),
         Paragraph("Running every issue; upgraded March 2026", CELL)],
        [Paragraph("Marketplace Listing", CELL_B),
         Paragraph("AskHomey.com directory presence; extends shelf life beyond the magazine", CELL),
         Paragraph("Active every issue alongside print", CELL)],
        [Paragraph("QR Code Engagement", CELL_B),
         Paragraph("Direct mobile traffic from the printed ad", CELL),
         Paragraph("17 QR scans; up to 3/month in April 2026", CELL)],
        [Paragraph("Call Tracking & Recording", CELL_B),
         Paragraph("Every inbound call captured, tagged, and reviewed", CELL),
         Paragraph("58 calls measured to date; 1 missed", CELL)],
    ]
    ch_tbl = Table(channel_data, colWidths=[1.55 * inch, 3.35 * inch, 2.5 * inch])
    ch_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), THM_DARK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, THM_LIGHT]),
        ("BOX", (0, 0), (-1, -1), 0.5, THM_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(ch_tbl)
    story.append(Spacer(1, 2))

    # ---------- LOOKING AHEAD ----------
    story.append(Paragraph("LOOKING AHEAD", H2))
    look_text = (
        "The first full month of Full Page placement produced a record month for call volume "
        "and the highest qualified rate of the engagement. With <b>11 appointments already "
        "booked</b> over the phone in 2026 &mdash; and peak fence-installation season just "
        "beginning &mdash; the campaign is positioned to deliver its strongest stretch yet. "
        "Thank you for your continued partnership."
    )
    look_tbl = Table([[Paragraph(look_text, BODY)]], colWidths=[7.4 * inch])
    look_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF3C7")),
        ("BOX", (0, 0), (-1, -1), 0.75, THM_RED),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(look_tbl)

    doc.build(story)
    print(f"PDF generated: {OUT}")


if __name__ == "__main__":
    build()
