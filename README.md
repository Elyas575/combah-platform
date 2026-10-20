# Combah Procurement & Logistics — Website and Operations Platform — Version 1.1

A responsive, database-backed **China → Ghana** procurement and logistics web platform built from the supplied *Combah Procurement & Logistics Concept Note*. It is an implementable **Version 1.1 / MVP**, not a production payment-processing service.

## Included

- **Public website:** services, process, all 16 Ghana regions, provisional price calculator, account entry.
- **Customer interface:** separate Buy for Me and Ship for Me workflows, preregistered independent purchases, permanent `CMB-GH-000001` reference, Buy for Me requests, order quotations, manual-payment reference submission, requests/packages/shipments, milestone history, regional address/profile, in-app notifications, and downloadable quotation/payment-acknowledgment PDFs.
- **Ship for Me:** customers preregister independently purchased parcels; warehouse and admin see expected arrivals; staff match via `CMB-SFM-` reference or uniquely matching supplier tracking. Customers can cancel unmatched preregistrations. No procurement fee is charged by this service.
- **China warehouse interface:** find customers by permanent ID, record unsolicited or order-linked goods, unique `CMB-PKG` IDs, optional weight/dimensions/damage/notes, prepare goods for shipment. Cannot verify payments or administer shipments.
- **Safety refinements:** dispatch requires a carrier/service or dispatch reference; only inspected, undamaged, ready parcels may be consolidated; damaged items need documented resolution; timelines are chronological with times.
- **Admin interface:** customer and staff list, manual payment verification, procurement actions, received packages, creation of consolidated shipments, controlled stage-by-stage shipment updates, immutable pricing on existing quotes, pricing/configuration, summary metrics and audit trail.
- **Backend:** FastAPI REST endpoints, SQLite data persistence, salted PBKDF2 password hashes, random DB-backed HttpOnly sessions, CSRF protection, role authorization, notifications and operational events, sequential shipping statuses.

## Run a local demonstration

Requires Python 3.10+.

```bash
cd combah-platform
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
COMBAH_DEMO=1 uvicorn app:app --reload --port 8000
```

On Windows you can also double-click `START_DEMO_WINDOWS.bat` from the new project folder, after Python and the requirements have been installed.

On Windows Command Prompt (CMD), run `set COMBAH_DEMO=1` and then `python -m uvicorn app:app --reload --port 8000`.

On Windows PowerShell, run `$env:COMBAH_DEMO="1"` before `uvicorn app:app --reload --port 8000`.
Open **http://127.0.0.1:8000**. This creates a local demo database (`data/combah.sqlite3`) with illustrative records. The login page offers demo-account shortcuts.

| Demo role | Email | Password |
| --- | --- | --- |
| Customer | `customer@combah.demo` | `DemoPass!2026` |
| China warehouse | `warehouse@combah.demo` | `DemoPass!2026` |
| Administrator | `admin@combah.demo` | `DemoPass!2026` |

**Never deploy demo credentials or sample records.** Set `COMBAH_DEMO=0` for production and use a fresh empty data directory. The fixed demo credentials are created **only** with `COMBAH_DEMO=1` against a database without a demo admin.

## Upgrading from Combah V1 on Windows without losing your existing data

1. In your current CMD window, press **Ctrl+C** to stop the V1 server. **Do not delete the old folder or database.**
2. Unzip the **V1.1** download into a **new** folder, so its new `combah-platform` project is separate from the old `combah-platform`.
3. In the old project folder find `data/combah.sqlite3`. Copy the **entire** `data` folder (after stopping the old server) into the new `combah-platform` folder. Back up the original first. If the original has no `data` folder, skip this step and V1.1 will create new demo records instead.
4. In the new project folder, click the Windows Explorer address bar, type `cmd`, press Enter, then run:

   ```cmd
   python -m pip install -r requirements.txt
   set COMBAH_DEMO=1
   python -m uvicorn app:app --reload --port 8000
   ```

5. Open `http://127.0.0.1:8000`. You can also start the new demonstration by double-clicking `START_DEMO_WINDOWS.bat` after installing the requirements. Existing V1 accounts and demonstration orders/packages are preserved. The first V1.1 startup creates new tables automatically without deleting the old records.
6. Check the new **Ship for Me** and **My shipping requests** pages as a customer, **Expected arrivals** as China warehouse, and **Ship for Me requests** as admin.

Do **not** copy a demo database into a public production site. The above migration is for your **local testing data only**. On a real customer database, take a verified backup and test the upgrade on a staging copy first.

## Start production on an Ubuntu VPS with Docker Compose

1. Register a domain you own and configure its DNS A/AAAA records to point to your server.
2. Install Docker Engine and the Docker Compose plugin on the VPS.
3. Copy this project onto the VPS. Copy `.env.example` to `.env` and set `COMBAH_DOMAIN` to your actual purchased domain. Do not commit `.env` to version control.
4. Run `docker compose up -d --build` and confirm that HTTPS is working. Caddy handles certificate issuance and renewal automatically when DNS and ports 80/443 are correct.
5. Create the first real admin account:
   ```bash
   docker compose exec app python manage.py create-admin
   ```
6. Sign in, configure **pricing, verified support details and the real China warehouse address**. Do not instruct customers to ship packages to an unverified address.
7. Set up daily backups of the persistent `app_data` Docker volume, monitor errors and configure your hosting provider's firewall. Keep app and proxy images patched.

**Security:** Production sets `COMBAH_SECURE_COOKIES=1`, which requires HTTPS. Staff passwords must be unique. Do not seed the demo database in production. Use external host/provider controls for DDoS and distributed login-rate limiting. SQLite is suitable for a low-volume single-host MVP; plan a managed PostgreSQL migration before heavy multi-server scaling.

## Before accepting real customer money

These items require owner/vendor decisions, verified business information or extra integration work and are intentionally **not claimed as operational**:

1. **Live payment collection:** select an approved Ghana payment processor, execute onboarding/KYC, integrate payment checkout/webhooks, verify signatures and test reconciliation/refunds. Currently the platform supports only **manual references requiring administrator verification**. No funds are transferred by this website.
2. **Financial & delivery policies:** legal terms, privacy notice, cancellation/refund rules, customs duties/taxes, prohibited-goods policy, loss/damage liability, shipping insurance, consumer support and escalation procedures. Obtain professional/legal review for Ghana and cross-border obligations.
3. **Confirmed logistics data:** physical China warehouse address, China partner agreement, freight/carrier/tracking arrangements, Ghana customs/clearance responsibilities, serviceable pickup partners and actual shipping price schedules.
4. **Quotation accuracy:** real-time conversion among RMB/USD/GHS, exchange-rate lock periods, volumetric weight, duty estimates, warehouse measurement adjustments and authorization of supplemental charges. V1 accepts **product prices already converted to GHS**, with provisional shipping costs.
5. **Production account security and operations:** verified email delivery, email verification, self-service password resets, 2FA for staff, delivery receipts, customer support tickets, anti-fraud controls, centralized operational alerts and off-site backups/recovery tests.
6. **Automated messaging:** SMS/WhatsApp notifications and external freight APIs are *future integrations*. In-app notifications work today.

## Data and API

Persistent data is in `data/combah.sqlite3` by default. Do not upload this file to GitHub or send it to customers. To reset local demo data, stop the server and remove `data/combah.sqlite3*` (deletes all data). Swagger API documentation is served at `/api/docs` for technical use.

See also `RELEASE_NOTES_V1.1.md`.

**This source bundle does not include an actually registered domain, hosting subscription, live warehouse integration, processor account, or published deployment.** Those require the appropriate accounts, provider choices and owner authorization. The provided Docker/Caddy setup is intended for a low-cost VPS, not ephemeral filesystem hosts such as a plain Vercel Function.
