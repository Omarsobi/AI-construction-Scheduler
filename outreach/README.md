# Outreach: Harvey for Omar's remote scheduling services

Email prospecting engine built on [Harvey](https://github.com/ethanplusai/harvey) (MIT). It finds small US construction firms, profiles them, and drafts cold emails for Omar's remote scheduling, takeoff and project controls work. It runs alongside LinkedIn prospecting, which Omar does by hand.

Harvey itself is cloned into `outreach/harvey/` (gitignored). Only Omar's customization lives in this repo:

| File | Purpose |
|---|---|
| `harvey.local.yaml` | Full Harvey config: persona, services, ICP, send limits, compliance. Replaces `harvey.yaml` entirely. |
| `skills/product_knowledge.md` | Services, buyer angles, writing rules, reply handling. Injected into every Harvey agent. |
| `patches/two-email-sequence.patch` | Writer change: 2 emails per pitch (first plus one follow-up at 7 days) instead of Harvey's 3. |
| `setup.sh` | Clones Harvey at the pinned commit, applies the patch, symlinks the two files above, installs the venv, runs `harvey status --check`. |

## Setup

```bash
bash outreach/setup.sh
cd outreach/harvey && source .venv/bin/activate
harvey signals --confirm HIRING_ROLE,OPEN_ROLES,CONTACT_FOUND,DECISION_MAKER_TITLE,LIKELY_OWNER,EMAIL_STATUS
```

Windows: `powershell -ExecutionPolicy Bypass -File outreach\setup.ps1`, then `.venv\Scripts\activate`. Python 3.11+.

Then `.env` in `outreach/harvey/` needs, at minimum, the Gmail OAuth client (`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, then `harvey gmail auth`) and one verifier key (`REOON_API_KEY` is the best free tier). Discovery works best with `SERPER_API_KEY` or DataForSEO; OpenStreetMap covers contractors poorly.

## Hard rules

- `require_approval` stays `true`. Every email waits in the Outbox for Omar.
- `linkedin.enabled` stays `false`.
- Only verified addresses are sent to (`send_to_risky: false`).
- No rates, client names, project names or results in any email unless Omar approved them.
- Never say or imply Omar is US-based or available onsite.

## First cohort

Small GCs and CMs in a few target states whose careers page lists a scheduler or project controls role:

```bash
harvey discover --estimate                           # cost first, always
harvey discover --preset hiring --provider serper
```

Limit: Harvey reads Greenhouse, Lever, Ashby, Workable or the firm's own careers page. Firms posting only on Indeed are missed.

## Before the first campaign (Omar's to-do)

1. Dedicated sending domain (not his Gmail) with a Google Workspace mailbox. Put the address in `persona.email`.
2. SPF, DKIM, DMARC on that domain. Check with `harvey warmup`.
3. 2 to 4 weeks of warmup. Set `channels.email.warmup.start_date`. This is the real bottleneck.
4. Postal address for the CAN-SPAM footer in `compliance.postal_address`.
5. Confirm `persona.company` matches LinkedIn.
6. Domains for `compliance.do_not_contact` (current clients and warm contacts).
7. Narrow `icp.geography` to the first target states or cities.
