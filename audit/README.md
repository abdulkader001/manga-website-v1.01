# Audit

Project-wide and frontend audit reports. Backend reports live next to the code
they describe.

| Report | What it covers |
| --- | --- |
| [full-audit-2026-10-02.md](full-audit-2026-10-02.md) | Full nine-pass audit (F-86 – F-98): reproduced security findings, speed on small servers, translation overlay check, recommendations |
| [ROADMAP.md](ROADMAP.md) | **Start here.** Numbered to-do list of fixes and hardening, with status; updated as items are done |
| [project-verdict-2026-09-30.md](project-verdict-2026-09-30.md) | What was built, what was verified, mismatches, ordered recommendations |
| [frontend.md](frontend.md) | Frontend build/dependencies, CSP vs external icons, login gate, mismatches, removed files |
| [../backend_fastapi/audit/](../backend_fastapi/audit/README.md) | Backend security review and design notes |

Deployment files: [../deployment/](../deployment/README.md) (web/nginx) and
[../backend_fastapi/deployment/](../backend_fastapi/deployment/README.md) (API,
workers, backups, Kubernetes).
