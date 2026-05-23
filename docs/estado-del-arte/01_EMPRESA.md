# 01 — Empresa

[← Volver al índice](../ESTADO_DEL_ARTE.md)

---

## Identidad legal

- **Razón social**: SkyFinanzas SpA
- **RUT**: 78.395.382-K
- **País**: Chile
- **Marca**: Sky / Sky Finanzas. Personaje IA = **Mr. Money**.
- **Dominios**: `skyfinanzas.com` (landing), `app.skyfinanzas.com` (aplicación), `api.skyfinanzas.com` (backend).
- **Contacto**: info@skyfinanzas.com · seguridad/vulnerabilidades: fintyinc@gmail.com

## Cofundadores

| Nombre | RUT | Rol |
|---|---|---|
| Cristian Cristóbal Amaru Vásquez Guevara | 22.141.522-1 | Arquitectura técnica y producto |
| Juan José Latorre Pérez | 22.003.365-1 | Estrategia, operación y diseño conductual |

## Propiedad intelectual

El modelo arquitectónico, la doctrina y la visión de Sky están consolidados en el documento **`SkyFinanzas_EstadoDelArte_v5_Documentado.pdf`**, **registrado ante INAPI** (Instituto Nacional de Propiedad Industrial, Chile). Es la fuente de verdad doctrinal y legal del producto.

El v5 está dividido en:
- **Parte I** — Estado verificado (lo implementado en producción).
- **Parte II** — Arquitectura objetivo (migración Python — Fases 0-13). *Hoy completada.*
- **Parte III** — Plan de remediación de deuda (P0/P1/P2 + BUG-1..4).
- **Parte IV** — Visión, gobierno, doctrina permanente.
- **Anexo A** — Estructura de repositorios.

> **Nota de mantenimiento**: el v5 fue registrado cuando la migración Python era *futuro*. A mayo 2026 está completa. Cuando se actualice el registro INAPI, la Parte II debe reescribirse como estado actual. Este documento markdown es el reflejo técnico vigente mientras tanto.

## Tesis del producto

La gente no falla en sus finanzas por falta de conocimiento, sino por **ansiedad, evasión y fricción**. La tecnología debe **absorber complejidad**, no exigir expertise. Sky es la capa cognitiva entre la persona y su vida financiera.

La promesa central es **respiratoria antes que cognitiva**: la landing dice *"Respira. Tus finanzas están en las mejores manos"*. El primer entregable emocional es alivio.

## Tres pilares

1. **Automatización bancaria** — conexión y consolidación sin esfuerzo del usuario.
2. **Interpretación inteligente** — Mr. Money traduce datos en claridad accionable.
3. **Diseño conductual** — metas, desafíos, simulaciones que cambian comportamiento.

## Visión estratégica — 5 fases de negocio

(No confundir con las 13 fases técnicas de migración, ya cerradas.)

| Fase | Objetivo |
|---|---|
| **F1 — Demostrar alivio** | Que un usuario sienta más claridad en una semana. Cierre de deuda P0 + migración Python. **← etapa actual** |
| **F2 — Consolidar hábito** | Recomendación entre pares. Más bancos. Fintoc + APIs directas. Entrada universitaria. |
| **F3 — Capa institucional** | ARIA genera valor B2B (bancos, gobierno, aseguradoras). |
| **F4 — Infraestructura** | Sky como plataforma. Contrato `DataSource` como API pública. |
| **F5 — Categoría regional** | Expansión Perú, México, Colombia. |

## Riesgos estratégicos vivos (v5 Parte IV §25)

Onboarding · complejidad acumulada · traición de datos · dependencia de proveedor · regulación (SFA) · sobrehype · talento · deuda técnica · ejecución de migración.

## Contexto de mercado relevante

- **Open Banking chileno (SFA)** está siendo desplegado por la **CMF**. Los bancos invierten en APIs sin tener aún consumers maduros que las usen con volumen. Sky se posiciona como ese consumer.
- Competidores adyacentes (no directos): Fintual (inversión), Mach/Tenpo (cuenta+pagos), RebajaTusCuentas. Sky **lee** esas cuentas; no compite como producto financiero, sino como capa de inteligencia y consolidación.
