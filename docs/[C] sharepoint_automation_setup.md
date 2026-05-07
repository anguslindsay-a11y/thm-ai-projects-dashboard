# SharePoint Automation — Setup Walkthrough

Reference doc for setting up automated SharePoint data ingestion into Supabase. Created during planning; update as steps complete.

## Big Picture

**Goal:** Replace manual SharePoint downloads (Inbox Advantage, Ad Placements, Ad JPGs) with an automated pipeline that runs in the cloud, logs every run, and alerts on failure.

**Architecture in one line:** SharePoint → Microsoft Graph API → GitHub Actions (cron) → Python ETL scripts → Supabase.

**Phases:**
1. Get Uncommon to set up access (the part that needs IT)
2. Build and test the connection locally
3. Build the pilot (IA), then roll out to Ad Placements and Ad JPGs
4. (Later) Migrate CallRail off the local Task Scheduler

Phase 1 is mostly a solo task for Masen. Phase 2+ happens in VS Code with Claude doing the heavy lifting.

---

## Phase 1 — Get Access Set Up with Uncommon

### Step 1: Gather the SharePoint site URLs

Before talking to Uncommon, identify the exact SharePoint sites holding our data. Uncommon will scope access only to these sites, not company-wide.

For each data source, open SharePoint in a browser, navigate to where the file/folder lives, and copy the **site URL** (just the part up through the site name, not the deeper folder path):

1. **Inbox Advantage spreadsheet** — what site?
2. **Ad Placements spreadsheet** — what site? (May be the same as IA.)
3. **Issue folders / Ad JPGs** — what site?

The URL format:
`https://thmmediawest.sharepoint.com/sites/[SiteName]`

Just the site root, not the full file path. If two sources share a site, list it once.

### Step 2: Send Uncommon a ticket

Copy-paste-ready ticket. Fill in the bracketed bits and send.

---

**Subject:** Setup Request — Microsoft Entra ID App Registration for SharePoint Automation

Hi [Uncommon contact],

I'm setting up an automated process that needs to read files from a few of our SharePoint sites on a schedule. Management has approved the project. Could you set up the following on the Microsoft side?

**1. Create an Entra ID app registration**
- Name: `THM Data Hub Automation` (or similar)
- Single-tenant (our organization only)

**2. Add API permissions** (application permissions, not delegated):
- `Microsoft Graph` → `Sites.Selected`
- `Microsoft Graph` → `Files.Read.All`
- Grant admin consent for both

If `Sites.Selected` isn't a fit on your end, the fallback is `Sites.Read.All` + `Files.Read.All`, but I'd prefer `Sites.Selected` since it's more restrictive.

**3. Grant the app read-only access to these specific SharePoint sites:**
- [paste site URL #1]
- [paste site URL #2]
- [paste site URL #3]

(For `Sites.Selected`, this is done via PnP PowerShell or Graph with the `Grant-PnPAzureADAppSitePermission` cmdlet, role = `read`.)

**4. Generate a client secret**
- Expiration: 24 months (longest available)
- Please save the expiration date so we can plan a renewal reminder.

**5. Send back to me (securely):**
- Tenant ID (Directory ID)
- Client ID (Application ID)
- Client Secret value
- Client Secret expiration date
- Confirmation of which sites were granted access

The app will only ever read files. It won't write, delete, or modify anything in SharePoint. Let me know if you have any questions or want to hop on a call.

Thanks,
Masen

---

### Step 3: Store credentials securely

When Uncommon replies, treat the values like passwords:

- Do NOT paste them into email or chat threads.
- Save to a password manager (1Password, Bitwarden, etc.). One entry: "THM Data Hub — Entra ID App", containing all four values (Tenant ID, Client ID, Client Secret, expiration date).
- The Client Secret is the sensitive one. Tenant ID and Client ID are not secret, but treat the bundle carefully.

### Step 4: Calendar reminder for secret renewal

Set a calendar reminder for **30 days before the secret expires** with the note: "Renew Entra ID client secret with Uncommon — pipeline will stop working when this expires."

This is the one ongoing operational gotcha. Getting it on the calendar now is the easy fix.

---

## Phase 2 — Build & Test the Connection (in VS Code with Claude)

Once credentials arrive:

1. Add credentials to `.env` (local only, never committed).
2. Build `etl/sharepoint_client.py` wrapper.
3. Write a tiny test script that fetches the IA spreadsheet and prints row count.
4. Confirm auth works end-to-end before building anything bigger.

This is the moment any permission gaps surface. If `Sites.Selected` was scoped wrong or a site was missed, easy fix — back to Uncommon with specifics.

---

## Phase 3 — Build the Pilot, Then Roll Out

After Phase 2 confirms file reads work:

1. Build the IA ETL (smallest, simplest first).
2. Set up GitHub Actions secrets and a workflow file.
3. Run manually a few times, verify results match current manual import.
4. Enable the schedule.
5. Add the `etl_runs` audit table and failure alerts.
6. Repeat for Ad Placements.
7. Build Ad JPG sync last — review filename convention first to decide auto-linking strategy.

---

## What Could Go Wrong in Phase 1

- **Uncommon pushes back on `Sites.Selected`.** Some IT shops don't have PnP PowerShell ready. Accept `Sites.Read.All` + `Files.Read.All` as fallback. Slightly broader, still read-only, still secure.
- **Uncommon asks about data classification.** Answer: client billing data, ad placement schedules, ad creative files. No PII beyond business contact info, no payment card data.
- **Uncommon takes a while to respond.** One-time setup, not urgent. Follow up after a week.
- **Credentials sent via insecure email.** Politely ask for the Client Secret via a secure channel (ticket-system secure note, password-share tool). Tenant ID and Client ID are fine in regular email.

---

## Decisions Already Made

- **Compute:** GitHub Actions (not Task Scheduler, not Power Automate, not local OneDrive sync).
- **Auth:** App-only (client credentials), not delegated. Service account, not personal login.
- **Permission scope:** `Sites.Selected` preferred, `Sites.Read.All` + `Files.Read.All` fallback.
- **Ad JPG storage:** Mirror to Supabase Storage (decision pending — revisit when building Phase 3 step 7).
- **CallRail migration:** Pending — leave on Task Scheduler until SharePoint pipeline is proven.
- **Alerting:** Pending — Slack and/or email, decide before Phase 3 step 5.

## Open Decisions (revisit before Phase 3)

1. Ad JPG storage approach (mirror to Supabase Storage vs. reference URLs).
2. Alerting channel (Slack vs. email vs. both).
3. Filename convention for Ad JPGs that enables auto-linking to placements.
