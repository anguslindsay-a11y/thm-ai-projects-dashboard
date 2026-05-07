"""Build a one-page side-by-side PDF of Dun-Rite's current ads (April 2026 / 2604)
across all four CO zones, for the rep meeting prep packet.
"""
from __future__ import annotations

import io
import os
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image as PILImage

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
)

REPO = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO / "output"
load_dotenv(REPO / ".env")

# Storage paths for the 4 current Dun-Rite zone ads (issue 2604, April 2026, 1/2 Page K&B)
ADS = [
    {
        "zone": "EPC", "zone_name": "El Paso County",
        "path": "THM Colorado 2026-04/Dun Rite Kitchen & Bath-THMCO-H-EPC-2604.jpg",
        "size": "1/2 Page",
        "headline": "You have our word, we'll treat you right at Dun-Rite",
        "offer": "Spring Scheduling Incentive — Save 8% with Select Install Dates",
    },
    {
        "zone": "ND", "zone_name": "North Denver",
        "path": "THM Colorado 2026-04/Dun Rite Kitchen & Bath-THMCO-H-NDN-2604.jpg",
        "size": "1/2 Page",
        "headline": "You have our word, we'll treat you right at Dun-Rite",
        "offer": "Spring Scheduling Incentive — Save 8% with Select Install Dates",
    },
    {
        "zone": "NOCO", "zone_name": "Northern Colorado",
        "path": "THM Colorado 2026-04/Dun Rite Kitchen & Bath-THMCO-H-NCO-2604.jpg",
        "size": "1/2 Page",
        "headline": "You have our word, we'll treat you right at Dun-Rite",
        "offer": "Spring Scheduling Incentive — Save 8% with Select Install Dates",
    },
    {
        "zone": "SD", "zone_name": "South Denver",
        "path": "THM Colorado 2026-04/Dun Rite Kitchen & Bath-THMCO-H-SDN-2604.jpg",
        "size": "1/2 Page",
        "headline": "You have our word, we'll treat you right at Dun-Rite",
        "offer": "Spring Scheduling Incentive — Save 8% with Select Install Dates",
    },
]


def fetch_image(storage_path: str) -> bytes:
    """Pull a private-bucket file via the Supabase Storage API."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    # URL-quote the path
    from urllib.parse import quote
    encoded = quote(storage_path)
    endpoint = f"{url}/storage/v1/object/client_ads/{encoded}"
    r = requests.get(endpoint, headers={"Authorization": f"Bearer {key}", "apikey": key})
    r.raise_for_status()
    return r.content


def to_image_flowable(img_bytes: bytes, max_width: float, max_height: float) -> Image:
    """Convert raw image bytes to a reportlab Image scaled to fit."""
    pil = PILImage.open(io.BytesIO(img_bytes))
    iw, ih = pil.size
    ratio = min(max_width / iw, max_height / ih)
    return Image(io.BytesIO(img_bytes), width=iw * ratio, height=ih * ratio)


def build():
    today = date.today()
    stamp = f"{today.month}-{today.day}-{today.year}"
    out_path = OUTPUT_DIR / f"[C] Dun-Rite Ads Side-by-Side {stamp}.pdf"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out_path), pagesize=landscape(letter),
        leftMargin=0.4*inch, rightMargin=0.4*inch,
        topMargin=0.4*inch, bottomMargin=0.4*inch,
        title="Dun-Rite Current Ads", author="THM Media",
    )

    styles = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=15, spaceAfter=4,
                        textColor=colors.HexColor("#1F4E78"))
    SUB = ParagraphStyle("Sub", parent=styles["BodyText"], fontSize=9, leading=11,
                         textColor=colors.HexColor("#404040"), spaceAfter=8)
    ZONE = ParagraphStyle("Zone", parent=styles["BodyText"], fontSize=10,
                          fontName="Helvetica-Bold", alignment=1,
                          textColor=colors.HexColor("#1F4E78"))
    AD_FOOT = ParagraphStyle("AdFoot", parent=styles["BodyText"], fontSize=7, leading=9,
                             alignment=1, textColor=colors.HexColor("#606060"))

    story = []
    story.append(Paragraph("Dun-Rite Kitchens &amp; Baths — Current Print Ads (All 4 CO Zones)", H1))
    story.append(Paragraph(
        f"Issue 2604 (April 2026) · 1/2 Page · Generated {today:%B %d, %Y} for rep meeting prep",
        SUB))

    # Fetch images
    print("Fetching ad images from Supabase Storage...")
    cells = []
    for ad in ADS:
        print(f"  {ad['zone']}: {ad['path']}")
        img_bytes = fetch_image(ad["path"])
        img = to_image_flowable(img_bytes, max_width=4.6*inch, max_height=3.0*inch)
        cell_block = [
            Paragraph(f"{ad['zone_name']} ({ad['zone']})", ZONE),
            Spacer(1, 3),
            img,
            Spacer(1, 3),
            Paragraph(f"{ad['size']} · Issue 2604", AD_FOOT),
        ]
        cells.append(cell_block)

    # 2x2 grid
    grid = Table(
        [[cells[0], cells[1]], [cells[2], cells[3]]],
        colWidths=[5.0*inch, 5.0*inch],
        rowHeights=[3.6*inch, 3.6*inch],
    )
    grid.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#BFBFBF")),
        ("INNERGRID", (0,0), (-1,-1), 0.5, colors.HexColor("#BFBFBF")),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(grid)
    story.append(Spacer(1, 8))

    # Footer with shared offer/headline summary
    summary = (
        "<b>Headline (all zones):</b> &ldquo;You have our word, we&rsquo;ll treat you right at "
        "Dun-Rite&rdquo;  &nbsp;|&nbsp;  "
        "<b>Offer:</b> Spring Scheduling Incentive — Save 8% with Select Install Dates  "
        "&nbsp;|&nbsp;  "
        "<b>Financing:</b> Bank financing options available  &nbsp;|&nbsp;  "
        "<b>CTA:</b> Free, no-obligation in-home quote · Book Now"
    )
    story.append(Paragraph(summary, SUB))

    doc.build(story)
    return out_path


if __name__ == "__main__":
    p = build()
    print(f"Wrote: {p}")
