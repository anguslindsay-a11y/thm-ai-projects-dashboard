"""Build the HVAC Category Performance client-facing PDF — concise version for prospects."""

from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)

OUTPUT = Path(__file__).resolve().parent.parent / "output" / "[C] HVAC Category Performance - Client Facing.pdf"
OUTPUT.parent.mkdir(exist_ok=True)

NAVY = HexColor("#1A3A5C")
ACCENT = HexColor("#D95D39")
GRAY = HexColor("#5C6370")
LIGHT = HexColor("#F2F4F7")
BORDER = HexColor("#D0D5DD")

styles = getSampleStyleSheet()
title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontName="Helvetica-Bold",
                              fontSize=18, textColor=NAVY, spaceAfter=1)
subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontName="Helvetica",
                                 fontSize=9, textColor=GRAY, spaceAfter=10)
h1_style = ParagraphStyle("H1", parent=styles["Heading2"], fontName="Helvetica-Bold",
                           fontSize=11, textColor=NAVY, spaceBefore=8, spaceAfter=3)
body_style = ParagraphStyle("Body", parent=styles["Normal"], fontName="Helvetica",
                             fontSize=9, textColor=black, leading=11.5, spaceAfter=3)
body_bold_style = ParagraphStyle("BodyBold", parent=body_style, fontName="Helvetica-Bold")
small_style = ParagraphStyle("Small", parent=styles["Normal"], fontName="Helvetica-Oblique",
                              fontSize=8, textColor=GRAY, leading=10)
bullet_style = ParagraphStyle("Bullet", parent=body_style, leftIndent=14, bulletIndent=4, spaceAfter=2)
cell_style = ParagraphStyle("Cell", parent=body_style, fontSize=9, leading=11, spaceAfter=0)


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
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=letter,
        leftMargin=0.5 * inch, rightMargin=0.5 * inch,
        topMargin=0.45 * inch, bottomMargin=0.4 * inch,
    )
    story = []

    # Title
    story.append(Paragraph("HVAC Advertising with TheHomeMag", title_style))
    story.append(Paragraph(
        "Performance snapshot: April 2025 – April 2026 | Colorado, Utah, Austin, San Antonio",
        subtitle_style,
    ))

    # At a glance
    story.append(Paragraph("The category at a glance", h1_style))
    story.append(Paragraph(
        "16 HVAC businesses currently advertise with TheHomeMag across 4 markets. Over the last "
        "12 months, the category generated <b>2,110 tracked calls</b> and <b>1,132 qualified leads</b> "
        "— homeowners actively looking for HVAC service.",
        body_style,
    ))

    # Seasonality
    story.append(Paragraph("When HVAC leads peak", h1_style))
    season = [
        ["", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"],
        ["Qualified", "167", "193", "179", "97", "74", "68", "101", "53", "46", "24", "48", "67"],
    ]
    cw = [1.1 * inch] + [0.5 * inch] * 12
    t = Table(season, colWidths=cw)
    style = ts()
    # Highlight peak months
    for col in (1, 2, 3):  # Apr, May, Jun
        style.add("BACKGROUND", (col, 1), (col, 1), HexColor("#FFE8DC"))
        style.add("FONTNAME", (col, 1), (col, 1), "Helvetica-Bold")
    t.setStyle(style)
    story.append(t)
    story.append(Spacer(1, 3))
    story.append(Paragraph(
        "April through June delivers <b>48% of the entire year's qualified leads</b>. "
        "Advertisers in the magazine by spring capture the full wave.",
        body_style,
    ))

    # Top performers
    story.append(Paragraph("What top HVAC advertisers are seeing", h1_style))
    perf = [
        ["Advertiser", "Market", "Qualified leads (12mo)", "Qual rate", "What they run"],
        ["Affordable Plumbing, Heating & Electrical", "CO", "153", "73.9%", "1/2 Page + Marketplace Listing"],
        ["RBuck", "CO", "125", "70.2%", "Full Page + Marketplace Listing"],
        ["McCullough Heating & Air", "Austin", "89", "63.6%", "Full Page + Back Cover Banner"],
        ["Air Central USA", "Austin", "82", "71.9%", "Full Page"],
    ]
    wrapped = [perf[0]]
    for row in perf[1:]:
        wrapped.append([
            Paragraph(row[0], cell_style), row[1], row[2], row[3],
            Paragraph(row[4], cell_style),
        ])
    t = Table(wrapped, colWidths=[2.4 * inch, 0.7 * inch, 1.5 * inch, 0.8 * inch, 2.1 * inch])
    t.setStyle(ts())
    story.append(t)
    story.append(Spacer(1, 3))
    story.append(Paragraph(
        "<b>Affordable Plumbing, Heating &amp; Electrical</b> averages <b>12.8 qualified leads per month</b>, "
        "every month — with ~87% of callers being first-time customers. They run a 1/2 Page ad, print only.",
        body_style,
    ))

    # Digital
    story.append(Paragraph("Digital engagement: QR codes + Inbox Advantage email", h1_style))
    story.append(Paragraph(
        "<b>Apex Clean Air (Utah)</b> runs Full Page ads across all Utah zones and drives engagement "
        "through <b>QR codes on their print ad</b> — <b>560 scans</b> in 12 months, proving the magazine "
        "drives action beyond phone calls. Apex is booked through 2026 with 56 orders across Utah and Colorado.",
        body_style,
    ))
    story.append(Spacer(1, 2))
    story.append(Paragraph(
        "HVAC advertisers who bundle Inbox Advantage email campaigns see <b>12–13% click-through rates</b> "
        "— roughly 4× the industry average.",
        body_style,
    ))
    dig = [
        ["Advertiser", "Market", "QR Scans", "Email Clicks"],
        ["Apex Clean Air", "Utah", "560", "1,911"],
        ["EcoLife HVAC", "Utah", "52", "5,011"],
        ["McCullough Heating & Air", "Austin", "—", "3,939"],
    ]
    t = Table(dig, colWidths=[2.8 * inch, 1.2 * inch, 1.5 * inch, 1.5 * inch])
    style = ts()
    style.add("BACKGROUND", (0, 1), (-1, 1), HexColor("#E8F4F8"))
    style.add("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold")
    t.setStyle(style)
    story.append(t)

    # What's working
    story.append(Paragraph("What's working", h1_style))
    for line in [
        "<b>Most popular:</b> Full Page + Marketplace Listing — what most top performers run",
        "<b>Budget-friendly:</b> 1/2 Page + Marketplace Listing — our #1 performer runs this size",
        "<b>Digital add-on:</b> Inbox Advantage email — 12–13% CTR, roughly 4× industry average",
        "<b>Premium visibility:</b> Back Cover Banner — McCullough and other top performers feature this",
    ]:
        story.append(Paragraph(f"• {line}", bullet_style))

    # Why now
    story.append(Paragraph("Why now", h1_style))
    for line in [
        "Lead volume <b>triples April–June</b> — spring is the window",
        "Multi-trade shops consistently hit <b>70–80% qualification rates</b>",
        "Only <b>16 HVAC businesses</b> currently advertise — room for a strong new entrant",
    ]:
        story.append(Paragraph(f"• {line}", bullet_style))

    # Footer
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Based on TheHomeMag call tracking data, April 2025 – April 2026. Qualified = homeowner "
        "conversations of substance, excluding voicemails, wrong numbers, and spam.",
        small_style,
    ))

    doc.build(story)
    print(f"Saved: {OUTPUT}")


if __name__ == "__main__":
    build()