# ADR: Gestión de Secretos — Decisión y Roadmap

> Fecha: 2026-05-10 | Estado: Activo | Cierra: R4

---

## Contexto

Sky Finance maneja secretos críticos:
- `BANK_ENCRYPTION_KEY` — clave AES-256-GCM para credenciales bancarias
- `SUPABASE_SERVICE_KEY` — acceso sin RLS a base de datos
- `ANTHROPIC_API_KEY` — acceso a API de IA
- `CRON_SECRET`, `PROMETHEUS_SECRET` — secretos operativos

La decisión de cómo gestionarlos afecta la seguridad, complejidad operativa y
la posibilidad de superar auditorías bancarias (ISO27001, CMF, SBIF).

---

## Opciones evaluadas

### Opción A: Variables de entorno en Railway (ELEGIDA para MVP)

**Pros**: cero complejidad, sin dependencias adicionales, suficiente para etapa actual.  
**Contras**: auditoría básica de acceso, rotación manual, no hay versionado automático.  
**Riesgo**: si Railway es comprometido, secretos expuestos. Mitigado por: TLS en transit,
acceso restringido al dashboard Railway (2FA obligatorio).

### Opción B: AWS Secrets Manager

**Pros**: auditoría completa (CloudTrail), rotación automática, versionado, KMS encryption.  
**Contras**: $0.40/secreto/mes + $0.05/10K llamadas, complejidad de setup inicial,
requiere SDK AWS en el código.  
**Cuándo adoptar**: cuando un banco o auditor ISO27001 lo exija explícitamente.

### Opción C: HashiCorp Vault (self-hosted)

**Pros**: control total, features enterprise, dynamic secrets.  
**Contras**: overhead operativo de mantener Vault HA. No apropiado para startup.  
**Cuándo adoptar**: si llegamos a escala donde el costo de Vault es justificado (Fase 4+).

---

## Decisión

**Opción A (Railway ENV vars)** para el MVP (Fases 11-12).

Condición de escalada: si un banco solicita due diligence técnico o una auditoría
ISO27001 lo requiere, migrar a **Opción B (AWS Secrets Manager)**. Estimación de
trabajo: 2-3 días (agregar boto3, actualizar config.py para leer de SM, IAM roles).

---

## Plan de migración a AWS SM (cuando aplique)

1. Crear secretos en AWS SM con los mismos nombres.
2. Agregar `boto3` a dependencies.
3. En `config.py`: si `USE_AWS_SECRETS_MANAGER=true`, leer de SM en lugar de ENV.
4. IAM Role para Railway task (OIDC o access key con mínimos privilegios).
5. Test de rotación automática con lambda rotator.
6. Retirar ENV vars de Railway.

---

*Revisión obligatoria si: se suma un banco como cliente institucional, auditoría bancaria,
o el equipo supera 5 personas con acceso a prod.*
