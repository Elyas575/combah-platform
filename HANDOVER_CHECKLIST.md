# Combah Website — Handover and Launch Checklist

## Implemented and tested

- Public website with Buy for Me, Ship for Me, region information and pricing estimator.
- Three dashboards, all using the same persistent database.
- Account registration, credentials, sessions and role restrictions.
- Customer ID matching, order quote snapshots, payment-reference requests.
- Payment approval only by administrator, before procurement can proceed.
- China warehouse package reception, package IDs and optional measurement fields.
- Package assignment into consolidated international shipments, sequential progress statuses.
- In-app notifications, audit history, downloadable quotations and verified-payment acknowledgments.
- Admin-managed pricing rules, warehouse address and support contact information.
- Docker/Caddy configuration for future owned-domain hosting and HTTPS.
- Automated backend smoke tests (`python -m unittest discover -s tests -v`).

## Must be supplied or verified by Combah before real launch

- [ ] Official company contact email and phone number.
- [ ] Confirmed China warehouse city, street address, contact person and warehouse operating agreement.
- [ ] Actual Ghana clearance/pickup/delivery arrangements; district coverage is not guaranteed.
- [ ] Approved procurement fees, actual freight tariffs, import taxes/duties and FX method.
- [ ] Real payment method and independently verified payment instructions.
- [ ] Public Terms of Service, Privacy Policy, Refund/Returns Policy, restricted goods, damage/insurance and customs terms, reviewed by an appropriate professional.
- [ ] Owner-approved domain name, provider selection, hosting budget and DNS configuration.
- [ ] Backups, TLS, admin credentials, monitoring, external abuse protection and restore rehearsal.

## Not represented as live features

Payment-provider checkout/webhooks, SMS/WhatsApp delivery, automatic carrier tracking, supplier APIs, verified email/password recovery, automated returns/refunds, duty calculation and real-time FX conversion.

**Do not give customers any payment or shipment instructions until the respective financial or warehouse arrangements have been verified by Combah.**
