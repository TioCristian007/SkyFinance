# 09 — Doctrina (23 reglas inviolables)

[← Volver al índice](../ESTADO_DEL_ARTE.md)

> Decisiones doctrinales firmadas por los cofundadores **antes** de la primera línea de código en producción. Sobreescriben conveniencia de corto plazo. No se negocian durante construcción.
> Fuente: v5 §26 + §13.2 + §14.4 + §15.4 + Parte III §20 (registrado ante INAPI).

---

## I. Producto

1. **El producto debe sentirse ligero.** La ligereza es feature, no limitación.
2. **Mr. Money guía; no decide.** Toda propuesta estructurada requiere confirmación explícita del usuario.
3. **La confianza vale más que cualquier monetización rápida.**
4. **El frontend NO es la fuente de verdad.** Toda lógica crítica vive en el backend.
5. **Los datos del usuario existen primero para servir al usuario.**

## II. Arquitectura

6. **La arquitectura desacopla** proveedor bancario, lógica de negocio y analytics.
7. **El dominio jamás pregunta de qué `source` vino un movimiento.** Si necesita distinguir origen, el modelo canónico está incompleto — se enriquece, no se rompe la abstracción.
8. **Modelo canónico único**: todo proveedor devuelve `CanonicalMovement`.
9. **La arquitectura tolera pivotes estratégicos.** Ningún proveedor/banco/integración es inamovible.
10. **La API Python NUNCA importa Playwright.** El worker es el único con browser pool. API y worker son procesos deployables independientes.

## III. Ingestión y resiliencia

11. **Scraper como fallback permanente.** Incluso tras APIs directas/SFA, queda como última línea. Solo se elimina si un contrato lo exige.
12. **`AuthenticationError` NO dispara failover.** La credencial es el problema; todos los proveedores la rechazarían.
13. **Rate limit = `skip`, no `fail`.** El siguiente provider de la cadena se intenta.
14. **Configuración como palanca operativa**: cambios de estrategia (activar BCI directo al 5%, mover Fintoc a primera línea) son `UPDATE` a `ingestion_routing_rules`, no deploys.

## IV. Seguridad

15. **`SUPABASE_SERVICE_KEY` y `BANK_ENCRYPTION_KEY` solo en backend.** Nunca en frontend, repo, ni logs.
16. **Credenciales bancarias = AES-256-GCM con IV único** (formato `iv:authTag:ciphertext`, compat binaria Node↔Python).
17. **IA (Anthropic) solo desde el backend.** Nunca desde el browser.
18. **RLS habilitado en TODAS las tablas de `public`.** Schema `aria` bloqueado a clientes (solo service_role escribe).
19. **Frontend NUNCA llama a Supabase con `service_role` ni a Anthropic directo.**
20. **Errores de scraper sanitizados** antes de mostrarse (eliminar password, rut, stack, timeouts).

## V. Privacidad

21. **ARIA solo se activa con `aria_consent = true`.** Sin UUID en `aria.*`. Service_role exclusivo.

## VI. Operación

22. **La deuda técnica se documenta, no se oculta.** Honestidad narrativa.
23. **La ambición debe merecerse con ejecución disciplinada.** Cada fase tiene gate de verificación; si el gate falla, la fase no está completa.

---

## Cómo se aplica

Estas reglas son **auditables contra el código**. Cuando un cambio propuesto contradice una de ellas, se rechaza en code review, sin negociación. Esa es la disciplina operativa del equipo.

Si una regla necesita cambiar, primero se actualiza el v5 (registro INAPI), después este documento. Nunca al revés.

---

**Firmado por:**
**Cristian Cristóbal Amaru Vásquez Guevara** — RUT 22.141.522-1
**Juan José Latorre Pérez** — RUT 22.003.365-1
Cofundadores · SkyFinanzas SpA · RUT 78.395.382-K
