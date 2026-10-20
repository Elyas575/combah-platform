# Combah 1.1 — Release notes

**Release:** 15 October 2026  
**Scope:** Upgrade of the working V1 FastAPI/SQLite platform. Three interfaces retained: Customer, China Warehouse, Admin. This is a locally tested MVP, **not** a commercially launched service.

## What changed

1. **Ship for Me (Customer).** A dedicated sidebar form to preregister items bought independently from a Chinese supplier. Customers can enter the supplier, tracking number, expected cartons/weight, destination and handling notes; review their shipping requests and cancel an unmatched preregistration. The platform generates a unique `CMB-SFM-000001` reference. It does not buy those goods or collect funds for them.
2. **Expected arrivals (China Warehouse and Admin).** Staff can see a list of preregistered parcels. The China warehouse receiving screen accepts an optional Ship for Me reference in addition to an optional Buy for Me procurement order. A customer package can be associated with either service, not both.
3. **Warehouse matching.** Receiving a physical package against the correct Customer ID and preregistration links the parcel to that request; a unique pending preregistration can also match by the same supplier tracking number. Packages received without a preregistration continue to work. Repeated supplier tracking numbers produce a warning rather than a hard block because legitimate shipments may have multiple cartons.
4. **Stricter consolidation.** Only packages physically marked **Ready for Shipping** and not flagged as damaged are eligible for a new shipment. Previously a newly received parcel could be included without warehouse readiness confirmation. Damaged goods require a documented inspection/resolution before being marked ready.
5. **Safer dispatch.** Updating a shipment to **In Transit** requires a freight carrier/service or a carrier/dispatch tracking reference. Later milestones retain that dispatch identity.
6. **Tracking readability.** Customer shipment histories are ordered from earliest to latest and display date, time and dispatch detail where recorded.
7. **Business configuration.** Admin has an optional indicative **Ship for Me handling fee** separate from the procurement charge. It is shown as guidance, **not** a payable invoice or automatic checkout.
8. **Non-destructive database upgrade.** Adds the `ship_requests` table and fee setting on startup without erasing existing V1 customer accounts, orders, packages or shipments.

## Included tests

`python -m unittest discover -s tests -v`

Covers role/CSRF checks, Buy for Me and payment-reference flow, package receipt and shipment milestones, Ship for Me preregistration and warehouse matching, cancellations, repeated tracking warnings, dispatch prerequisites and chronology. Tests use a temporary sample database. Existing V1 database migration was also checked separately with the original V1 sample dataset.

## Known boundaries before commercial launch

- Payments are **manual-reference review only**; real gateways, refunds, partial payments and processor reconciliation are not connected.
- No real China warehouse address, real carrier API/tracking feed, SMS/WhatsApp delivery, live foreign-exchange rates or externally verified shipping tariffs is configured.
- The Ship for Me preregistration indicates expected goods only; official freight/handling invoices and measured-weight reconciliation remain operational processes to define with the client.
- Terms of service, privacy, claims for loss/damage, customs handling, prohibited goods policy, and Ghana regulatory compliance require approval before public use.
- Staff MFA, email verification/password reset, production backups, security assessment and HTTPS deployment must be completed before live customers use the service.
- Domain registration and first-year hosting are **not purchased or activated** by the source code package.

The `README.md` contains Windows installation and data-preserving upgrade instructions.
