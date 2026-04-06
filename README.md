# Sky Finance

Plataforma de finanzas personales con IA integrada, analytics anonimizados (ARIA) y autenticación persistente.

> Stack: Node.js + Express · React + Vite · Anthropic Claude · Supabase

---

## Arquitectura

```
sky-finance/
├── backend/
│   ├── server.js
│   ├── .env.example
│   ├── package.json
│   ├── data/                    ← vacío, Supabase es la fuente de verdad
│   ├── routes/
│   │   ├── chat.js              ← POST /api/chat → Mr. Money
│   │   ├── transactions.js      ← GET/POST/DELETE /api/transactions
│   │   ├── summary.js           ← GET /api/summary
│   │   ├── challenges.js        ← GET + activate/complete /api/challenges
│   │   ├── simulate.js          ← POST /api/simulate
│   │   └── goals.js             ← CRUD /api/goals
│   └── services/
│       ├── aiService.js         ← Mr. Money: prompt + Anthropic SDK
│       ├── financeService.js    ← lógica financiera (async, usa dbService)
│       ├── dbService.js         ← todas las operaciones de Supabase app
│       ├── supabaseClient.js    ← dos clientes: anon + admin (service role)
│       └── ariaService.js       ← pipeline ARIA: anonimización + analytics
│
└── frontend/
    ├── index.html
    ├── vite.config.js
    ├── .env.example
    ├── package.json
    └── src/
        ├── App.jsx              ← orquestador auth: loading|auth|onboarding|app
        ├── Sky.jsx              ← app principal, recibe userId como prop
        ├── main.jsx
        ├── services/
        │   ├── api.js           ← único canal al backend
        │   └── supabase.js      ← cliente Supabase frontend + auth helpers
        ├── components/
        │   ├── AuthScreen.jsx       ← login + registro + Google OAuth
        │   ├── OnboardingScreen.jsx ← setup primera vez (nombre, edad, región, ingreso)
        │   ├── GoalCard.jsx         ← tarjeta de meta con barra de progreso
        │   ├── AddGoalForm.jsx      ← formulario crear meta
        │   ├── AddSavingsModal.jsx  ← modal agregar ahorro a una meta
        │   ├── DonutChart.jsx
        │   ├── CatBars.jsx
        │   ├── TxItem.jsx
        │   ├── AddTxForm.jsx
        │   ├── ChatComponents.jsx
        │   └── ChallengeComponents.jsx
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
```

---

## Setup local

### 1. Clonar

```bash
git clone https://github.com/tu-org/sky-finance.git
cd sky-finance
```

### 2. Backend

```bash
cd backend
cp .env.example .env
# Editar .env con tus keys reales
npm install
npm run dev
# Corre en http://localhost:3001
```

### 3. Frontend

```bash
cd frontend
cp .env.example .env
# Editar .env con VITE_SUPABASE_URL y VITE_SUPABASE_ANON_KEY
npm install
npm run dev
# Corre en http://localhost:5173
```

### 4. Verificar

- `http://localhost:5173` → pantalla de login
- `http://localhost:3001/api/health` → `{"status":"ok"}`

---

## Variables de entorno

### `backend/.env`

| Variable | Descripción |
|---|---|
| `ANTHROPIC_API_KEY` | API key de Anthropic — console.anthropic.com |
| `SUPABASE_URL` | URL del proyecto Supabase |
| `SUPABASE_ANON_KEY` | Anon key de Supabase (pública) |
| `SUPABASE_SERVICE_KEY` | Service role key — solo backend, nunca frontend |
| `PORT` | Puerto del servidor (default: 3001) |

### `frontend/.env`

| Variable | Descripción |
|---|---|
| `VITE_API_URL` | URL del backend (default: http://localhost:3001/api) |
| `VITE_SUPABASE_URL` | URL del proyecto Supabase |
| `VITE_SUPABASE_ANON_KEY` | Anon key de Supabase |

---

## Supabase — setup inicial

Ejecutar `aria_schema.sql` en Supabase SQL Editor. Crea:

**Esquema `public` (app, con RLS):**
- `profiles` — UUID + display_name, age_range, region, income_range, points
- `transactions` — vinculadas a user_id
- `goals` — metas financieras por usuario
- `challenge_states` — estado de desafíos por usuario
- `earned_badges` — badges ganados

**Esquema `aria` (analytics, sin UUID, bloqueado a clientes):**
- `spending_patterns` — patrones de gasto anonimizados
- `goal_signals` — señales de metas
- `behavioral_signals` — motivaciones extraídas por Mr. Money
- `session_insights` — comportamiento de navegación

---

## ARIA — Anonymized Randomized Intelligence Architecture

Pipeline de anonimización que corre en el backend antes de escribir en analytics:

1. **Extracción** — eventos reales → señales estructuradas (texto → categorías)
2. **Categorización** — valores exactos → rangos (edad → "26-35", monto → "50k-150k")
3. **Eliminación de identidad** — UUID removido antes de escribir en `aria.*`
4. **Randomización intra-bucket** — el valor guardado es random dentro del rango, no el real
5. **Ruptura de correlaciones** — cada campo tiene su propio `batch_id` random + jitter temporal

Resultado: dataset vendible a terceros sin posibilidad de reconstruir identidades.

---

## Auth y persistencia

- Supabase Auth maneja registro, login y Google OAuth
- La sesión se persiste en `localStorage` — el usuario no hace login en cada visita
- Flujo: `loading` → `auth` → `onboarding` (primera vez) → `app`
- `App.jsx` orquesta los estados; `Sky.jsx` recibe `userId` como prop

---

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/summary` | Resumen financiero + perfil + badges |
| GET | `/api/transactions` | Lista de transacciones |
| POST | `/api/transactions` | Agrega transacción (dispara ARIA) |
| DELETE | `/api/transactions/:id` | Elimina transacción |
| POST | `/api/chat` | Chat con Mr. Money |
| GET | `/api/challenges` | Estado de desafíos |
| POST | `/api/challenges/:id/activate` | Activa desafío |
| POST | `/api/challenges/:id/complete` | Completa desafío + Mr. Money celebra |
| POST | `/api/simulate` | Simulación de ahorro |
| GET | `/api/goals` | Lista de metas con proyección |
| POST | `/api/goals` | Crea meta (dispara ARIA) |
| PATCH | `/api/goals/:id` | Actualiza ahorro de una meta |
| DELETE | `/api/goals/:id` | Elimina meta |

---

## Estado del proyecto

| Capa | Estado |
|---|---|
| App React completa | ✅ |
| Backend Express modular | ✅ |
| Mr. Money (Anthropic) | ✅ |
| Metas financieras gamificadas | ✅ |
| Supabase conectado | ✅ |
| Auth + persistencia + Google | ✅ |
| Pipeline ARIA | ✅ |
| Deploy (Railway/Render) | 🔶 Pendiente |
| Open Banking / Fintoc | 🔶 Pendiente |

---

## Seguridad

- Las API keys **nunca** van en el código ni en el repo
- `SUPABASE_SERVICE_KEY` solo en el backend — nunca en el frontend
- El esquema `aria.*` está bloqueado a clientes — solo `supabaseAdmin` puede escribir
- RLS activado en todas las tablas de `public` — cada usuario solo ve sus propios datos
- Mr. Money llama a Anthropic **solo desde el backend**
