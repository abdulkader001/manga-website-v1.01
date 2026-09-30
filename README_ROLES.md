# Role Boundaries — Intended Design

> **This document describes the *intended* role model, not what the code does today.**
>
> The authoritative spec is [`TARGET_DESIGN_roles.md`](TARGET_DESIGN_roles.md) at the repo
> root; this file is a summary of it. **None of it is implemented yet.**
>
> For what the system actually enforces right now — including the `ADMIN`/`PERMANENT`
> collapse and the unconstrained secondary-admin promote/demote endpoints — see
> [`docs/system-reference/02-authorization-and-permissions.md`](docs/system-reference/02-authorization-and-permissions.md),
> which documents current implemented behavior only. Do not use this file to reason about
> what a given request will be allowed to do today.
>
> The prior version of this file claimed to describe current behavior and was wrong on
> three of twelve boundaries; see `docs/master-audit/pre-part-2-doc-verification.md` for
> the verification that established that. It has been replaced by the target design
> rather than corrected in place.

## Four tiers, no more

`USER` → `MODERATOR` → `SECONDARY_ADMIN` → `PERMANENT_ADMIN`

The separate non-permanent `ADMIN` rank that exists in the code today is **retired** under
this design. There is no fifth tier.

## `USER`

Normal authenticated user. No administrative capability.

## `MODERATOR`

Community moderation tier. Reports performance, login activity, and actions up to the
Secondary Admin who manages them.

## `SECONDARY_ADMIN`

- **Manages a pool of up to 10 moderators at a time** — a live capacity, not a lifetime
  counter. Demoting a moderator frees a slot; a replacement can then be promoted, keeping
  the total at 10.
- **Promote/demote authority is limited strictly to the `USER` ↔ `MODERATOR` boundary.**
  A Secondary Admin **cannot** promote anyone to `SECONDARY_ADMIN` — no peer promotion.
  Only the Permanent Admin creates a new Secondary Admin.
- **Every demotion requires a stated reason**, which is sent as a notification to the
  Permanent Admin when it happens.
- **Cannot toggle any of their own permissions.** Whatever the Permanent Admin has granted
  is simply active; there is no self-service control panel.
- Their own activity is reported up to the Permanent Admin **automatically** — system
  generated, not self-submitted.

## `PERMANENT_ADMIN`

- Full authority to change any user's role/tier, including granting and revoking
  `SECONDARY_ADMIN` and `MODERATOR` directly.
- A dedicated admin-management screen listing every Secondary Admin and Moderator.
- From that screen, for any individual: toggle their permissions on/off **and/or** change
  their role/tier. The two are independent — changing what someone can do does not require
  changing their tier.

## Reporting chain

`MODERATOR` → reports to → `SECONDARY_ADMIN` → reports to → `PERMANENT_ADMIN`

## Open questions

Three implementation questions are deliberately left undecided (pool scoping, orphaned
moderators when a Secondary Admin is removed, notification delivery mechanism). They are
listed in `TARGET_DESIGN_roles.md` and belong on Part 2/3's design-decision list — they
should not be guessed at during implementation.
