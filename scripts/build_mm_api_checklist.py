"""Build a one-page meeting checklist PDF for the MagManager API discussion."""

from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
)
from reportlab.lib.enums import TA_LEFT

OUT = Path(__file__).resolve().parent.parent / "output" / "[C] MagManager API Meeting Checklist.pdf"
OUT.parent.mkdir(exist_ok=True)

NAVY = HexColor("#1f3a5f")
ORANGE = HexColor("#e07a1f")
GREY = HexColor("#5a5a5a")
LIGHT = HexColor("#f3f3f3")

styles = getSampleStyleSheet()

H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName="Helvetica-Bold",
                   fontSize=18, textColor=NAVY, spaceAfter=4, leading=22)
SUB = ParagraphStyle("SUB", parent=styles["Normal"], fontName="Helvetica-Oblique",
                     fontSize=10, textColor=GREY, spaceAfter=12, leading=12)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName="Helvetica-Bold",
                    fontSize=12, textColor=ORANGE, spaceBefore=10, spaceAfter=4, leading=14)
ITEM = ParagraphStyle("ITEM", parent=styles["Normal"], fontName="Helvetica",
                      fontSize=10, textColor=HexColor("#222222"), leading=13,
                      leftIndent=14, bulletIndent=0, spaceAfter=2)
NOTE = ParagraphStyle("NOTE", parent=styles["Normal"], fontName="Helvetica-Oblique",
                      fontSize=9, textColor=GREY, leading=11,
                      leftIndent=14, spaceAfter=4)


def cb(text, sub=None):
    """Build a checkbox-prefixed paragraph, with optional grey sub-line below."""
    items = [Paragraph(f"☐&nbsp;&nbsp;{text}", ITEM)]
    if sub:
        items.append(Paragraph(sub, NOTE))
    return KeepTogether(items)


def section(title, items):
    flow = [Paragraph(title, H2)]
    flow.extend(items)
    return flow


def main():
    doc = SimpleDocTemplate(
        str(OUT), pagesize=LETTER,
        leftMargin=0.55 * inch, rightMargin=0.55 * inch,
        topMargin=0.5 * inch, bottomMargin=0.5 * inch,
        title="MM API Meeting Checklist",
    )

    story = []

    story.append(Paragraph("MagManager API — Meeting Checklist", H1))
    story.append(Paragraph(
        "Discussion with Mel · Goal: agree on scope and field list so MM can size the work.",
        SUB,
    ))

    story.extend(section("1. Confirm scope", [
        cb("Limit new/extended access to <b>CO, UT, SA</b> databases only.",
           "Skip East Bay, SoCal, NW — they're already on existing endpoints."),
        cb("Extend existing <b>api_ContactsGet</b> / <b>api_OrdersGet</b> where possible — avoid new endpoints unless necessary."),
    ]))

    story.extend(section("2. Rep activity endpoint (new)", [
        cb("Confirm endpoint covers <b>notes, callbacks, meetings, tasks, emails, voicemails</b>."),
        cb("Request parameters: <b>CustomerID, RepID, From/To DateAdded, ModifiedSince</b>.",
           "ModifiedSince is critical — without it daily ETL re-pulls full history."),
        cb("Response fields beyond their defaults: <b>NoteType/ActivityType, Subject, DateModified, CompletionStatus, Outcome/Disposition</b>."),
    ]))

    story.extend(section("3. Custom fields — biggest unblocker", [
        cb("<b>Ask for the full list</b> of customer-level and order-level custom fields configured in CO/UT/SA.",
           "Field name, data type, sample values. Avoids guessing and back-and-forth."),
        cb("Confirm these specific fields exist (or closest equivalent): <b>industry/category/subcategory, account lifecycle, internal flags/tags, production notes on orders</b>."),
        cb("Preference: customer fields added to <b>api_ContactsGet</b>, order fields to <b>api_OrdersGet</b> — not new endpoints."),
    ]))

    story.extend(section("4. Additional data points to confirm", [
        cb("<b>Contact email addresses + phone numbers</b> on customer records.",
           "Replaces our manual cross-platform mapping spreadsheet."),
        cb("<b>Cancellation reasons</b> — captured anywhere queryable?"),
        cb("<b>Contract / agreement data</b> — start, end, term length, autorenew."),
        cb("<b>Status change history</b> — log of customer status transitions, not just current state."),
        cb("Confirm <b>api_UsersGetPowerBI</b> returns: rep ID, name, market assignment, active flag, hire/end dates."),
    ]))

    story.extend(section("5. Incremental sync — non-negotiable", [
        cb("Add <b>ModifiedSince</b> (or equivalent timestamp filter) to every endpoint we'll consume daily.",
           "Drives sync cost. Without it, every run pulls full history."),
    ]))

    story.extend(section("6. Write endpoints — gauge availability", [
        cb("Are <b>write/update endpoints</b> available now or on roadmap?"),
        cb("Specifically: updating customer custom fields, creating notes/activities programmatically, bulk field cleanup.",
           "Not committing to build — just want to know if it's possible."),
        cb("If write requires different auth model, separate tier, or signed agreement — capture that."),
    ]))

    story.extend(section("Questions to leave the meeting with answers to", [
        cb("Timeline: when can the read expansion ship?"),
        cb("Will MM send the full custom-fields list, or do we need to enumerate fields blind?"),
        cb("Does ModifiedSince exist anywhere today, or is it new build?"),
        cb("Are write endpoints possible at all, even at higher cost / restricted access?"),
        cb("Pricing — does this expansion change our API costs?"),
    ]))

    # Footer-ish bottom strip
    story.append(Spacer(1, 0.15 * inch))
    footer = Table(
        [[Paragraph(
            "<font color='#5a5a5a' size='8'><b>Top priorities to walk away with:</b> "
            "(1) full custom-fields list, (2) ModifiedSince support on every endpoint, "
            "(3) yes/no on write endpoints.</font>", styles["Normal"])]],
        colWidths=[7.4 * inch],
    )
    footer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.5, NAVY),
    ]))
    story.append(footer)

    doc.build(story)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
