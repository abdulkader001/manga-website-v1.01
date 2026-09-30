# TARGET DESIGN — Role & Permission Model (Not Yet Implemented)

**Status: design spec only.** Nothing in this document describes current code behavior. It exists so this design isn't lost between the audit and the eventual fix/build phase. Current actual behavior is documented separately in `README_ROLES.md`'s prior sibling `docs/system-reference/02-authorization-and-permissions.md` (not included in this repository).

## Role hierarchy — four tiers, no more

`USER` → `MODERATOR` → `SECONDARY_ADMIN` → `PERMANENT_ADMIN`

The current code's separate non-permanent `ADMIN` rank is retired under this design. There is no fifth tier. (This directly resolves reconciliation items #10–#13 and the ADMIN/PERMANENT-collapse finding from the doc verification pass — but as a deliberate redesign, not a bug patched back to the old four/five-tier intent.)

## Secondary Admin

**Moderator pool — capacity of 10, not a lifetime counter:**

- Manages up to 10 moderators at a time (promote `USER` → `MODERATOR`).
- Demoting a moderator (`MODERATOR` → `USER`) frees one slot in the pool.
- Can then promote a replacement, keeping the total at 10.
- A demotion requires the Secondary Admin to give a reason. That reason is sent as a notification to the Permanent Admin when the demotion happens.

**No peer promotion:** a Secondary Admin cannot promote anyone to `SECONDARY_ADMIN`. Their promote/demote authority is limited strictly to the `USER` ↔ `MODERATOR` boundary described above. Only the Permanent Admin can create a new Secondary Admin.

**Reporting up:**

- Every moderator under a Secondary Admin reports their performance, login activity, and actions to that Secondary Admin.
- Each Secondary Admin's own activity is reported up to the Permanent Admin automatically — a system-generated report, not something the Secondary Admin writes or submits manually.
- Chain: `MODERATOR` → reports to → `SECONDARY_ADMIN` → reports to → `PERMANENT_ADMIN`.

**No self-service permission control:** a Secondary Admin cannot toggle any of their own permissions on or off. Whatever the Permanent Admin has granted them is simply active — the Secondary Admin has no control panel for it. Only the Permanent Admin can turn a Secondary Admin's permissions on or off.

## Permanent Admin

- Full authority to change any user's role/tier, including granting or revoking `SECONDARY_ADMIN` and `MODERATOR` status directly.
- A dedicated admin-management screen listing every Secondary Admin and Moderator in the system.
- From that screen, can open any individual admin/moderator and:
  - Toggle their individual permissions on/off (e.g., grant a specific Secondary Admin the "add new moderators" capability) — this changes what they can do without changing their role/tier.
  - Change their role/tier outright. Both capabilities exist simultaneously — toggling permissions and changing roles are not mutually exclusive actions.

## What this replaces / conflicts with in current code and docs

- **Current code:** `_is_main_admin` (`dependencies/auth.py:149-159`) makes `ADMIN` and `PERMANENT` indistinguishable — this design makes that collapse intentional rather than a bug, by removing the `ADMIN` tier outright.
- **Current code:** `require_admin_user` admits Secondary Admins to unrestricted promote/demote endpoints (`admin.py:1993,2029,2072,2113`) with no pool cap and no reason/report requirement — this design adds both constraints.
- **`README_ROLES.md` (original):** stated Secondary Admin "CANNOT change roles" at all — this design explicitly allows a constrained version of that, limited strictly to the `USER` ↔ `MODERATOR` boundary. Secondary Admin still cannot create, promote to, or demote from `SECONDARY_ADMIN` or `PERMANENT_ADMIN` under any circumstance.
- **`docs/system-reference/02-authorization-and-permissions.md` (not included in this repository):** documents the current unconstrained implementation as-is — this design narrows and structures it.

## Open implementation questions for whoever builds this (not decided here)

- Is the 10-moderator pool per Secondary Admin, or a global cap shared across all Secondary Admins? (Read from context: per Secondary Admin.)
- What happens to a Secondary Admin's pool of moderators if that Secondary Admin is itself demoted or removed?
- Exact notification delivery mechanism for demotion reasons and Secondary Admin activity reports (in-app, email, both) — not specified above.

These should go to Part 2/3's design-decision list, not be guessed at during implementation.
