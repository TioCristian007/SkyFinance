# Archivo histórico — documentación de construcción de Sky

> Registro de **cómo** se construyó Sky. Conservado por doctrina (§22: "la deuda se documenta, no se oculta") y para auditoría / onboarding / INAPI.
> **No es documentación vigente.** Para el estado actual ver `docs/ESTADO_DEL_ARTE.md`.

---

## Contenido

### Migración Python (13 fases — todas cerradas, mayo 2026)
- `MIGRATION_13_PHASES.md` — plan maestro técnico de la migración Node → Python.
- `FASE6/7/9/10/11/12_CLOSURE_PLAN.md` — planes de cierre por fase.
- `FASE11_DEPLOY_CHECKLIST.md` — checklist de despliegue (env vars históricas).
- `HANDOVER_FASE_9.md` — handover scheduler.
- `SPRINT_FASE_6_7_PROMPT.md`, `SPRINT_PHASE_C_DOCKER_FIX_PROMPT.md` — prompts de sprint.

### Post-cutover y debug (mayo 2026)
- `POST_CUTOVER_PLAN.md`, `POST_CUTOVER_AUDIT.md`, `POST_CUTOVER_DEBUG_AUDIT.md`, `POST_CUTOVER_CLOSURE.md`.
- `SPRINT_POST_CUTOVER_PROMPT.md`, `SPRINT_CORS_DEBUG_PROMPT.md`, `SPRINT_DEBUG_E2E_PROMPT.md`.
- `SPRINT_POSTCUTOVER_BANKING_REVIVAL.md` — revival de conexión bancaria post-cutover.
- `SPRINT_SCRAPERS_P0.md` — sprint de scrapers (cola ARQ, income display, listado bancos).

Archivado el 2026-05-23 al consolidar el Estado del Arte integral.
