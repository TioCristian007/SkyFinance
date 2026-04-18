## License

This project is **source-available, proprietary software**.

You are allowed to **view and evaluate the source code for personal or educational purposes only**.

❌ Commercial use  
❌ Redistribution or mirroring  
❌ Derivative works  
❌ Production deployment  
❌ Use of this code or architecture to train AI models  

All rights reserved © 2026 Cristian Cristobal Amaru Vásquez Guevara.

See the [LICENSE](./LICENSE) file for full terms.


# Sky Finance

Plataforma de finanzas personales con IA, conexión bancaria automática, analytics anonimizados (ARIA) y autenticación persistente.

> **Stack:** Node.js + Express · React + Vite · Anthropic Claude · Supabase · AES-256-GCM · open-banking-chile

---

## Qué es Sky

Sky es un sistema operativo financiero personal de baja fricción. Conecta las cuentas bancarias del usuario, categoriza sus transacciones automáticamente, y pone a **Mr. Money** — un copiloto financiero con IA — a disposición para explicar la situación, aterrizar metas y sugerir mejoras de hábito.

El producto existe para reducir ansiedad financiera, evasión y fricción mental. No es una app de gastos. No es una app de educación financiera. Es una capa entre el usuario y su vida financiera que absorbe complejidad y devuelve claridad.

---

## Arquitectura

```
sky-finance/
├── backend/
│   ├── server.js                  ← punto de entrada + verificación de encriptación
│   ├── middleware/
│   │   └── auth.js                ← extrae userId del header Authorization
│   ├── routes/
│   │   ├── banking.js             ← conexión bancaria, sync, cuentas
│   │   ├── chat.js                ← POST /api/chat → Mr. Money
│   │   ├── transactions.js        ← GET/POST/DELETE /api/transactions
│   │   ├── summary.js             ← GET /api/summary
│   │   ├── goals.js               ← CRUD /api/goals
│   │   ├── challenges.js          ← GET + activate/complete /api/challenges
│   │   └── simulate.js            ← POST /api/simulate
│   └── services/
│       ├── aiService.js           ← Mr. Money: contexto financiero + Anthropic SDK
│       ├── ariaService.js         ← pipeline ARIA: anonimización + analytics
│       ├── bankingAdapter.js      ← abstracción de proveedor bancario
│       ├── bankSyncService.js     ← orquestador de sync bancario
│       ├── categorizerService.js  ← categorización 3 capas (reglas + caché + IA)
│       ├── dbService.js           ← operaciones Supabase app
│       ├── encryptionService.js   ← AES-256-GCM para credenciales bancarias
│       ├── financeService.js      ← lógica financiera (cálculos, proyecciones)
│       └── supabaseClient.js      ← dos clientes: anon + admin (service role)
│
└── frontend/
    ├── index.html
    ├── vite.config.js
    └── src/
        ├── App.jsx                ← orquestador auth: loading|auth|onboarding|app
        ├── Sky.jsx                ← coordinador principal, recibe userId como prop
        ├── components/
        │   ├── AuthScreen.jsx         ← login + registro + Google OAuth
        │   ├── OnboardingScreen.jsx   ← setup primera vez
        │   ├── BankConnect.jsx        ← conectar y sincronizar bancos
        │   ├── GoalCard.jsx           ← meta con barra de progreso
        │   ├── AddGoalForm.jsx
        │   ├── AddSavingsModal.jsx
        │   ├── ChatComponents.jsx     ← interfaz Mr. Money
        │   ├── ChallengeComponents.jsx
        │   ├── MrMoneyProposal.jsx    ← propuestas estructuradas del agente
        │   ├── SimulationChart.jsx
        │   ├── DonutChart.jsx
        │   ├── CatBars.jsx
        │   ├── TxItem.jsx
        │   └── AddTxForm.jsx
        ├── services/
        │   ├── api.js             ← único canal al backend
        │   └── supabase.js        ← cliente Supabase + auth helpers
        ├── data/
        │   ├── categories.js
        │   ├── challenges.js
        │   ├── colors.js
        │   └── simulations.js
        └── utils/
            └── format.js
```

---

## Regla de oro

```
Frontend  →  solo muestra, captura y llama al backend
Backend   →  calcula, decide, guarda, llama a la IA
IA        →  solo desde el backend, nunca desde el browser
ARIA      →  solo escribe en analytics, nunca lee datos de usuarios
Cifrado   →  solo el backend conoce BANK_ENCRYPTION_KEY
```

---

## Setup local

### 1. Clonar

```bash
git clone https://github.com/TioCristian007/SkyFinance.git
cd SkyFinance
```

### 2. Backend

```bash
cd backend
cp .env.example .env
# Completar .env con las keys reales (ver tabla de variables abajo)
npm install
npm run dev
# Corre en http://localhost:3001
```

### 3. Frontend

```bash
cd frontend
cp .env.example .env
# Completar VITE_API_URL, VITE_SUPABASE_URL y VITE_SUPABASE_ANON_KEY
npm install
npm run dev
# Corre en http://localhost:5173
```

### 4. Verificar

```
http://localhost:5173         → pantalla de login
http://localhost:3001/api/health  → {"status":"ok","app":"sky-backend"}
```

---

## Variables de entorno

### `backend/.env`

| Variable | Descripción | Seguridad |
|---|---|---|
| `ANTHROPIC_API_KEY` | API key de Anthropic | Solo backend |
| `SUPABASE_URL` | URL del proyecto Supabase | — |
| `SUPABASE_ANON_KEY` | Anon key de Supabase | — |
| `SUPABASE_SERVICE_KEY` | Service role key — **nunca en frontend** | Solo backend |
| `BANK_ENCRYPTION_KEY` | Clave maestra AES-256-GCM para credenciales bancarias | Solo backend, crítica |
| `CHROME_PATH` | Ruta a Chrome/Chromium (auto-detecta macOS y Windows; en Linux: `/usr/bin/google-chrome`) | — |
| `BCHILE_2FA_TIMEOUT_SEC` | Segundos de espera para aprobación 2FA Banco de Chile (default: 120) | — |
| `PORT` | Puerto del servidor (default: 3001) | — |

### `frontend/.env`

| Variable | Descripción |
|---|---|
| `VITE_API_URL` | URL del backend (default: `http://localhost:3001/api`) |
| `VITE_SUPABASE_URL` | URL del proyecto Supabase |
| `VITE_SUPABASE_ANON_KEY` | Anon key de Supabase |

---

## Supabase — Setup de base de datos

Ejecutar los archivos SQL del directorio `SupabaseSQLQuerys/` en Supabase SQL Editor, en este orden:

1. `ARIA_sqlschema.txt` — esquema base completo (tablas `public` y `aria`, RLS, triggers)
2. `Bank_SQLSchema.txt` — tabla `bank_accounts` y columnas bancarias en `transactions`
3. `BDC_Migration.txt` — soporte `movement_source` para Banco de Chile
4. `transaction_categories.txt` — columnas adicionales en `profiles` (occupation, consentimiento ARIA, derecho al olvido)
5. `merchant_categories_chile.txt` — tabla caché de comercios categorizados
6. `behavioral.txt` — vistas analíticas ARIA

Todos los archivos son re-ejecutables (usan `IF NOT EXISTS`).

### Esquema `public` — datos del usuario (con RLS)

| Tabla | Propósito |
|---|---|
| `profiles` | UUID + preferencias de app. Sin nombre real, email, RUT ni documento. |
| `transactions` | Movimientos financieros. Soporta manual y bancario (bank_account_id, external_id). |
| `bank_accounts` | Cuentas bancarias conectadas. Credenciales AES-256-GCM. |
| `goals` | Metas financieras con seguimiento de avance. |
| `challenge_states` | Estado de desafíos por usuario. |
| `earned_badges` | Badges ganados. |
| `merchant_categories` | Caché global de categorías de comercios. Solo service_role. |

### Esquema `aria` — analytics anonimizados (bloqueado a clientes)

| Tabla | Contenido |
|---|---|
| `spending_patterns` | Patrones de gasto por bucket de monto y segmento demográfico. Sin UUID. |
| `goal_signals` | Señales de metas (tipo, tier, completion rate). Sin UUID. |
| `behavioral_signals` | Motivaciones y bloqueos financieros detectados por Mr. Money. Sin UUID. |
| `session_insights` | Comportamiento de navegación y uso de features. Sin UUID. |

---

## Bancos soportados

| Banco | Estado | Método |
|---|---|---|
| Banco Falabella | ✅ Activo | Scraper Puppeteer |
| Banco de Chile | ✅ Activo | Scraper Puppeteer + 2FA app |
| Santander Chile | 🔶 Pendiente | — |
| BCI | 🔶 Pendiente | — |
| Banco Estado | 🔶 Pendiente | — |

### Flujo de conexión bancaria

1. Usuario ingresa RUT y clave en `BankConnect.jsx`
2. Backend cifra ambos con AES-256-GCM → se almacena solo el ciphertext en Supabase
3. En cada sync: backend descifra en memoria → scraper extrae movimientos → adaptador normaliza → deduplicación → inserción → ARIA en background
4. Para Banco de Chile: el sistema detecta pantalla de 2FA y reporta `"⏳ Esperando aprobación..."` que el frontend lee via polling. El usuario aprueba en su app bancaria y el scraper continúa automáticamente.

### Cambiar de proveedor bancario

`bankingAdapter.js` es la única capa que conoce al proveedor externo. Migrar de `open-banking-chile` a Fintoc, Open Banking regulado u otro = modificar solo este archivo. El resto del sistema consume el modelo canónico.

---

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/summary` | Resumen financiero + perfil + badges + bancos conectados |
| GET | `/api/transactions` | Lista de transacciones |
| POST | `/api/transactions` | Agrega transacción (dispara ARIA si hay consentimiento) |
| DELETE | `/api/transactions/:id` | Elimina transacción |
| POST | `/api/chat` | Chat con Mr. Money |
| GET | `/api/challenges` | Estado de desafíos |
| POST | `/api/challenges/:id/activate` | Activa desafío |
| POST | `/api/challenges/:id/complete` | Completa desafío + Mr. Money celebra |
| POST | `/api/simulate` | Simulación de ahorro |
| GET | `/api/goals` | Lista de metas con proyección |
| POST | `/api/goals` | Crea meta (dispara ARIA si hay consentimiento) |
| PATCH | `/api/goals/:id` | Actualiza ahorro de meta |
| DELETE | `/api/goals/:id` | Elimina meta |
| GET | `/api/banking/banks` | Listado de bancos soportados |
| GET | `/api/banking/accounts` | Cuentas bancarias conectadas del usuario |
| POST | `/api/banking/accounts` | Conecta nueva cuenta bancaria |
| POST | `/api/banking/accounts/:id/sync` | Sincroniza cuenta (extrae movimientos) |
| DELETE | `/api/banking/accounts/:id` | Desconecta cuenta |

---

## ARIA — Anonymized Randomized Intelligence Architecture

Pipeline de anonimización que corre en el backend antes de escribir en analytics. Solo activo si el usuario dio consentimiento explícito (`aria_consent = true`).

1. **Extracción** — evento real → señal estructurada
2. **Categorización** — valor exacto → rango (monto → bucket, fecha → trimestre)
3. **Eliminación de identidad** — UUID removido antes de escribir en `aria.*`
4. **Randomización intra-bucket** — el valor guardado es random dentro del rango, no el real
5. **Ruptura de correlaciones** — jitter temporal ±36h, batch_id propio por registro

Resultado: dataset de comportamiento financiero chileno sin posibilidad de reidentificación individual.

---

## Seguridad

- Las API keys **nunca** van en el código ni en el repositorio
- `SUPABASE_SERVICE_KEY` y `BANK_ENCRYPTION_KEY` solo en el backend — nunca en el frontend
- Las credenciales bancarias se cifran AES-256-GCM con IV único antes de tocar Supabase
- El esquema `aria.*` está bloqueado a clientes — solo `supabaseAdmin` (service_role) puede escribir
- RLS activado en todas las tablas de `public` — cada usuario solo ve sus propios datos
- Mr. Money llama a Anthropic **solo desde el backend**
- El servidor verifica integridad de cifrado al arrancar (`verifyEncryptionReady()`)

---

## Estado del proyecto

| Capa | Estado |
|---|---|
| App React completa | ✅ |
| Backend Express modular | ✅ |
| Mr. Money (Anthropic) | ✅ |
| Metas financieras gamificadas | ✅ |
| Desafíos y badges | ✅ |
| Supabase Auth + persistencia + Google OAuth | ✅ |
| Conexión bancaria (Falabella + Banco de Chile + 2FA) | ✅ |
| Cifrado AES-256-GCM de credenciales bancarias | ✅ |
| Categorización 3 capas (reglas + caché + IA) | ✅ |
| Pipeline ARIA con consentimiento explícito | ✅ |
| Web pública (skyfinanzas.com) | ✅ |
| Deploy en producción (Railway / Render) | 🔶 Pendiente |
| Tests automatizados | 🔶 Pendiente |
| Open Banking regulado (SFA / Fintoc) | 🔶 Futuro |
| Santander, BCI, Banco Estado | 🔶 Futuro |

---

## Web pública

**[skyfinanzas.com](https://www.skyfinanzas.com)** — landing independiente en repo separado. HTML estático, tipografía Geist + Instrument Serif. Google Analytics G-TQ06VZE8SF.

---

*Sky Finance · v2.0 · Chile · 2026*