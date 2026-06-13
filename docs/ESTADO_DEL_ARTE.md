# Sky Finanzas — Estado del Arte Técnico (Integral)

> Documento maestro y único punto de entrada a la documentación técnica de Sky Finanzas.
> Refleja el estado **real y verificado** del sistema a la fecha de última actualización.
>
> **Fuente de verdad doctrinal**: `Estados del Arte/SkyFinanzas_EstadoDelArte_v5_Documentado.pdf` (registrado ante INAPI, Chile). Si algo aquí contradice al v5, gana el v5 — y este documento debe corregirse. Nota: el v5 describía la migración Python como *futuro (Parte II)*; **a mayo 2026 esa migración está completa y en producción**, por lo que este documento es el reflejo actualizado de esa realidad.

**Última actualización**: 2026-06-12 · **Mantenedores**: Cristian Vásquez · Juan José Latorre

---

## Cómo está organizado

Documentación **modular**. Este índice da el panorama; cada sección profundiza un dominio:

| # | Sección | Contenido |
|---|---|---|
| 01 | [Empresa](estado-del-arte/01_EMPRESA.md) | SkyFinanzas SpA, cofundadores, visión, tesis, fases de negocio, propiedad intelectual |
| 02 | [Producto](estado-del-arte/02_PRODUCTO.md) | Qué es Sky, Mr. Money, ARIA, categorización, metas y desafíos, promesa central |
| 03 | [Ecosistema](estado-del-arte/03_ECOSISTEMA.md) | Bancos soportados, contrato `DataSource`, modelo canónico, SFA, proveedores |
| 04 | [Arquitectura](estado-del-arte/04_ARQUITECTURA.md) | Stack, frontend/API/worker, IngestionRouter, flujos de datos |
| 05 | [Infraestructura](estado-del-arte/05_INFRAESTRUCTURA.md) | Railway (servicios reales), Supabase, Anthropic, DNS, dominios |
| 06 | [Configuración](estado-del-arte/06_CONFIGURACION.md) | Variables de entorno, secretos, colas ARQ, despliegue, CI |
| 07 | [Seguridad](estado-del-arte/07_SEGURIDAD.md) | Cifrado, RLS, anonimización ARIA, audit log, JWT, runbooks |
| 08 | [Estado y Deuda](estado-del-arte/08_ESTADO_Y_DEUDA.md) | Qué funciona, qué no, deuda P0-P3, hallazgos recientes |
| 09 | [Doctrina](estado-del-arte/09_DOCTRINA.md) | Las 23 reglas inviolables |

**Referencia operativa durable** (en `backend-python/docs/`): `API_CONTRACT.md`, `SECURITY.md`, `DECISION_SECRETS_MANAGER.md`, `DR_RUNBOOK.md`, `RUNBOOK_KEY_ROTATION.md`, `REMEDIATION_P0_P3.md`.

**Histórico** (en `backend-python/docs/archive/`): planes de cierre de las 13 fases, sprints, auditorías post-cutover. Es el registro de *cómo* se construyó Sky — se conserva por doctrina (§22: "la deuda se documenta, no se oculta").

---

## Resumen ejecutivo (TL;DR)

**Qué es Sky**: un sistema operativo financiero personal. Conecta las cuentas bancarias del usuario chileno, interpreta su comportamiento con IA (Mr. Money, sobre Claude) y devuelve claridad. La promesa es **alivio emocional** antes que cognitivo.

**Quién**: SkyFinanzas SpA (RUT 78.395.382-K), cofundada por Cristian Vásquez y Juan José Latorre. Modelo registrado ante INAPI.

**Estado técnico (junio 2026)**:
- Backend migrado de Node.js a **Python 3.12 (FastAPI + ARQ + Playwright)**. Las 13 fases de migración cerradas; cutover completo. Node archivado.
- Producción viva: `app.skyfinanzas.com` (frontend React) + `api.skyfinanzas.com` (API Python), sobre Railway + Supabase + Anthropic.
- ~1.283 transacciones reales procesadas. Categorización con feedback loop de 5 niveles (recategorizar/renombrar enseña) verificada en prod. 650 tests automatizados.
- **Sync BChile verificado end-to-end EN PRODUCCIÓN (2026-06-12)** — sprint ingesta cerrado: fill()+verificación post-fill, Chrome real en el worker, ciclo `needs_reconnection` anti-bloqueo, taxonomía de fallos + panel de operador. MVP para testers desbloqueado.
- **Onboarding de testers endurecido (2026-06-12, segunda tanda)**: detección positiva del 2FA "aprueba en tu app" sobre el form Auth0 (la ambigüedad ya no se castiga como clave mala), status `waiting_2fa` visible en la app (wiring de progreso que faltaba), cobertura completa del ciclo `needs_reconnection`, capturas debug PII-safe, panel operador con resumen por status. Node legacy apagado (B-6 cerrado).
- **Categorización que aprende (2026-06-12/13)**: Fase 1 (recategorizar enseña: voto per-user + consenso crowdsourced con quórum, frontera de privacidad) verificada en prod. Bloque 0 + Fase 2 construidos (pendiente migración 015 + deploy): el renombre de comercios enseña un alias per-user + nombre canónico global por consenso, con la misma frontera de identidad — las etiquetas de pasarela (`mercadopago*`, …) jamás se comparten porque no identifican UN comercio. Detalle en [08](estado-del-arte/08_ESTADO_Y_DEUDA.md).

**Lo que funciona**: ingesta canónica (BChile en prod), categorización, Mr. Money, ARIA, metas/desafíos, cifrado AES-256-GCM, RLS, audit log, data export Ley 19.628.

**Lo que NO funciona hoy** (ver [08](estado-del-arte/08_ESTADO_Y_DEUDA.md)):
- **Scraper BCI roto**: BCI cambió el dominio de su portal (`portalpersonas.bci.cl` ya no resuelve). Rework pendiente (sprint propio).
- Lentitud general sin profiling (B-5) · `Sky.jsx` god-component (P1-1).

**Dirección estratégica**: migrar de scraping a **SFA (Open Banking chileno, CMF)** en cuanto los bancos liberen sus APIs. El scraping queda como fallback. La fragilidad del scraping (anti-bot, cambios de portal) es precisamente el argumento para el SFA.

---

## Glosario rápido

| Término | Significado |
|---|---|
| **Mr. Money** | Asistente financiero conversacional de Sky, sobre Claude. Guía, no decide. |
| **ARIA** | Capa de analytics anónimos agregados. Consent explícito, sin UUID. |
| **DataSource** | Contrato abstracto de toda fuente de datos bancarios (5 tipos). |
| **CanonicalMovement** | Modelo único al que se normaliza todo movimiento, sin importar el origen. |
| **SFA** | Sistema Financiero Abierto — Open Banking regulado chileno (CMF). |
| **IngestionRouter** | Orquestador de proveedores con failover, circuit breaker y rate limit. |
| **v5** | El PDF doctrinal registrado ante INAPI; fuente de verdad legal. |
