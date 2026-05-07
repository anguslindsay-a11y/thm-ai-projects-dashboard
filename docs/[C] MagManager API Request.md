# MagManager API Expansion — Reply Draft

**Status:** Draft for review
**To:** MagManager support (replying to their May 2026 follow-up)
**Created:** 2026-05-06

---

## Subject
Re: API expansion — scope and specifics

---

## Body

Hi [name],

Thanks for the detailed breakdown — that helps a lot. Below is what we're looking for, organized so you can scope the work cleanly. Wherever possible we'd like to extend the existing endpoints rather than introduce new ones, so we don't disrupt what we've already built around them.

### 1. Scope: Colorado, Utah, San Antonio/Austin only

Yes — please limit the new/extended access to:

- thehomemagcolorado
- thehomemagutah
- thehomemagsanantonio

Other consumers on the existing endpoints (East Bay, SoCal, NW) shouldn't be affected.

### 2. Rep activity endpoint (new)

You've got our use case right — notes, activities, callbacks, meetings. A few additions to the response fields you proposed:

**Request parameters (we'd want all of these supported, any combination):**

- CustomerID
- RepID
- From/To DateAdded
- **ModifiedSince** — critical for incremental daily syncs so we're not re-fetching full history every run

**Response fields (your defaults plus the additions in bold):**

- CustomerID, Customer
- FirstName, LastName
- **NoteType / ActivityType** — note vs callback vs meeting vs email vs task vs voicemail (whatever your internal categorization uses)
- **Subject / Title** — separate from note body
- Note (body)
- RepName, RepID
- DateAdded, **DateModified**
- CallbackDate, MeetingDate
- **CompletionStatus** — for callbacks/meetings: pending, completed, cancelled, no-show
- **Outcome / Disposition** — if your system captures a result code or outcome on completed activities

### 3. Custom fields — both customer and order level

We want both. Rather than guessing field names, would you be able to **send us the full list of customer-level and order-level custom fields configured in our CO / UT / SA databases** (field name, data type, sample values)? That way we can pick exactly what we need and avoid back-and-forth.

Once we've reviewed that list, our preference is:

- **Customer custom fields** added to `api_ContactsGet` / `api_ContactsGetPowerBI` rather than a new endpoint — keeps our integration simpler.
- **Order/production custom fields** added to `api_OrdersGet` / `api_OrdersGetPowerBI` for the same reason.

Specific fields we already know we need (please confirm these exist or let us know the closest equivalent):

- Industry / category / subcategory
- Account lifecycle / status fields
- Internal flags or tags
- Production notes on orders (offer info, special instructions, anything beyond size/placement)

### 4. Additional data points worth including

A few things that aren't in the current endpoints and would close gaps for us:

- **Contact email addresses and phone numbers** on customer records — we currently match clients across platforms (CallRail, Inbox Advantage, etc.) using a manual mapping spreadsheet. Email + phone from MM would let us automate that linkage.
- **Cancellation reasons** — when a customer cancels, is the reason captured in a queryable field? If so we'd like it on `api_ContactsGet`.
- **Contract / agreement data** — start date, end date, term length, autorenew flag, anywhere these live.
- **Status change history** — a log of customer status transitions (active → cancelled → reactivated, etc.) over time, not just current state. If this lives anywhere accessible, we'd love a way to read it.
- **Sales rep roster** — please confirm what `api_UsersGetPowerBI` currently returns. We need rep ID, name, current market/database assignment, active/inactive flag, and start/end dates with the company if available.

### 5. Incremental sync support

Wherever feasible, please add a **ModifiedSince** parameter (or equivalent timestamp filter) to every endpoint we'll be consuming daily. Without it, every run pulls full history, which gets expensive at scale. With it, daily incrementals are cheap and we can run more frequent syncs as needed.

### 6. Write endpoints — availability?

Separate question, since the endpoints above are all read-only: **are write/update endpoints available now or on your roadmap?** Specifically we'd be interested in:

- Updating customer custom fields (e.g., correcting category values programmatically after a cleanup pass)
- Creating notes/activities under a customer (e.g., logging programmatic touches like automated email sends)
- Bulk customer field cleanup (standardizing names, fixing typos across many records)

We're not committing to building any of this yet — just want to gauge whether it's possible so we know whether to plan for it. If write access requires a different auth model, signed agreements, or a separate API tier, that's helpful context too.

### 7. Next steps

Happy to hop on a call if it'd be faster to walk through the custom fields list and clarify any of the above. Otherwise, the field list (item #3) is probably the biggest unblocker — once we've seen what's available, we can finalize exactly what to include in the response payloads.

Thanks again,
[your name]

---

## Notes for Masen (not part of the email)

- The "ModifiedSince" ask is the single most important technical detail — without it, daily ETL gets expensive fast as data grows.
- The custom fields list ask saves a back-and-forth. Worth pushing back if they want us to enumerate fields blind.
- Tier-2 (write endpoints) is phrased as a gauge, not a commitment, so they don't think we're scope-creeping the read request.
- If you want a tighter / shorter version, the cuttable sections are: #4 (additional data points — could trim to email+phone only) and the explanatory parentheticals throughout.
