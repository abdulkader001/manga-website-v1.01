# Audit

Project-wide and frontend audit reports. Backend reports live next to the code
they describe.

| Report | What it covers |
| --- | --- |
| [bug-test-2026-10-03.md](bug-test-2026-10-03.md) | **Newest.** Whole-site bug test in a real browser (guest, reader, owner, all admin pages): 8 bugs fixed, 7 open findings, the guides checked |
| [site-functions-tab-access-and-hardening-2026-10-03.md](site-functions-tab-access-and-hardening-2026-10-03.md) | Site Functions, Tab access, visitors' IP privacy, the route audit and 12 fixes |
| [storage-design.md](storage-design.md) | When and how to move pictures to S3 / a CDN (design only) |
| [fix-guide-2026-10-02.md](fix-guide-2026-10-02.md) | How an AI agent should fix each open finding (critical → low): when, where to look, what to change, pitfalls, how to prove it |
| [full-audit-2026-10-02.md](full-audit-2026-10-02.md) | Full nine-pass audit (F-86 – F-98): reproduced security findings, speed on small servers, translation overlay check, recommendations |
| [ROADMAP.md](ROADMAP.md) | **Start here.** Numbered to-do list of fixes and hardening, with status; updated as items are done |
| [project-verdict-2026-09-30.md](project-verdict-2026-09-30.md) | What was built, what was verified, mismatches, ordered recommendations |
| [frontend.md](frontend.md) | Frontend build/dependencies, CSP vs external icons, login gate, mismatches, removed files |
| [../backend_fastapi/audit/](../backend_fastapi/audit/README.md) | Backend security review and design notes |

Deployment files: [../deployment/](../deployment/README.md) (web/nginx) and
[../backend_fastapi/deployment/](../backend_fastapi/deployment/README.md) (API,
workers, backups, Kubernetes).
