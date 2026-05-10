# API Contract — Idempotency Key

> Aplica a: POST /api/banking/sync/{account_id}, POST /api/banking/sync-all,
> POST /api/banking/accounts

---

## Qué es

El header `Idempotency-Key` garantiza que un POST con side-effects no se ejecute
dos veces ante un retry del cliente. Si el servidor ya procesó una request con esa
key, devuelve la respuesta original (sin volver a ejecutar la operación).

## Cuándo usar

- Redes inestables (mobile, WiFi débil) donde el cliente no sabe si la request llegó.
- Retry automático del frontend tras un timeout aparente.
- Prevenir doble sync o doble conexión de cuenta.

## Formato

```
Idempotency-Key: <UUID v4>
```

El cliente genera un UUID v4 único por intento de operación. El servidor devuelve
la misma respuesta para todas las requests con la misma key durante 24 horas.

## Comportamiento del servidor

| Situación | HTTP | Headers | Body |
|-----------|------|---------|------|
| Primera request | Normal (200, 201, etc.) | — | Respuesta real |
| Retry con misma key | 200/201 (cached) | `X-Idempotency-Replay: true` | Respuesta original cacheada |
| Request en vuelo con misma key | 409 Conflict | `Retry-After: 5` | `{"error": "Request en progreso..."}` |
| Sin header Idempotency-Key | Normal | — | Respuesta real (sin dedup) |

## TTL

24 horas (configurable via `IDEMPOTENCY_TTL_SECONDS`). Tras 24h, la misma key
se trata como una nueva operación.

## Rutas donde aplica

```
POST /api/banking/sync/{account_id}
POST /api/banking/sync-all
POST /api/banking/accounts
```

Las rutas GET y DELETE no necesitan idempotency key (GET es idempotente por naturaleza,
DELETE es seguro de reintentar porque la segunda ejecución es no-op).

## Ejemplo de uso (JavaScript)

```javascript
const idkKey = crypto.randomUUID();

async function syncWithRetry(accountId, retries = 3) {
  for (let i = 0; i < retries; i++) {
    const resp = await fetch(`/api/banking/sync/${accountId}`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Idempotency-Key": idkKey,  // mismo UUID en todos los reintentos
      },
    });
    if (resp.status === 409) {
      await sleep(5000);  // Retry-After
      continue;
    }
    return resp;
  }
}
```
