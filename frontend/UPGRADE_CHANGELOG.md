# Sky Frontend — Corporate Upgrade Changelog

**Fecha:** Abril 2026  
**Objetivo:** Transformar la percepción de "demo tech con IA" a "producto financiero profesional y cercano"  
**Principio:** Una app bien hecha no necesita explicar que funciona.

---

## Archivos Modificados

| Archivo | Cambios |
|---------|---------|
| `Sky.jsx` | 15+ ediciones — el grueso del upgrade |
| `App.jsx` | Loading screen: logo real en vez de emoji |
| `components/AuthScreen.jsx` | Logo Sky real, nombre simplificado |
| `components/OnboardingScreen.jsx` | Logo real, lenguaje profesional |
| `components/BankConnect.jsx` | Logos de bancos reales, limpieza de lenguaje |
| `components/ChatComponents.jsx` | Avatar fallback SVG en vez de emoji |
| `public/assets/banks/*.png` | **NUEVO** — 5 logos reales de bancos chilenos |

---

## Cambios Detallados

### 1. Eliminación de elementos "IA/Demo"

- **"Powered by Claude"** — Eliminado del header del chat. Una app seria no expone su motor.
- **"En línea · listo para ayudarte"** — Reemplazado por "Asistente financiero". El tono WhatsApp-bot desapareció.
- **Badge "IA"** en navegación de Mr. Money — Eliminado. Mr. Money es parte del producto, no un feature que se etiqueta.
- **"Tu asesor financiero personal con IA"** → **"Tu copiloto financiero"** — Sin "con IA" innecesario.
- **"Sky Finance"** → **"Sky"** en AuthScreen — Más limpio, alineado con branding.
- **"Tu asesor financiero personal"** → **"Tu compañero financiero"** en onboarding.

### 2. Eliminación de indicadores de sync/status innecesarios

- **SyncBadge "SINCRONIZADO"** — Componente eliminado completamente + sus 2 usos (topbar, bancos).
- **SyncDot (punto verde pulsante)** — Eliminado de: dashboard momentum, ticker de movimientos, dashboard recientes.
- **"Cuentas sincronizadas"** → Muestra el conteo real ("2 cuentas conectadas") sin animación.
- **"Movimientos · en vivo"** → **"Últimos movimientos"** — Sin punto pulsante.
- **"ver el saldo real en vivo"** → **"ver tu saldo actualizado"**

### 3. Logos reales de bancos chilenos

Se agregaron logos PNG reales para 5 bancos:
- `banco-chile.png` — Banco de Chile (B gótica sobre navy)
- `falabella.png` — Banco Falabella (hojas verdes)
- `bci.png` — BCI (X multicolor)
- `santander.png` — Santander (llama roja)
- `bancoestado.png` — BancoEstado (edificio geométrico)

**Componente nuevo: `BankLogo`** — Renderiza el logo real con fallback a abreviación si la imagen falla. Usado en:
- `BankCardCompact` (dashboard sidebar)
- `BankCardFull` (página bancos)
- Dashboard inline bank rows (sección "Mis cuentas")

**Componente nuevo en BankConnect: `BankIcon`** — Mismo concepto para el flujo de conexión bancaria. Reemplaza emojis por logos en:
- Lista de cuentas conectadas
- Selector de banco al conectar
- Header del formulario de credenciales
- Lista de bancos próximamente

**BANK_META actualizado** con colores reales de cada banco y paths a logos.

### 4. Limpieza de BankConnect.jsx

- "Sincronizando..." → "Actualizando..."
- "🔄 Sincronizar" → "Actualizar"
- "sync completado" → "actualizado"
- "Disponible ahora" → "Disponible"
- "Chrome no encontrado. Verifica CHROME_PATH." → "Servicio de conexión no disponible. Intenta más tarde." (no exponer infra)
- "Error de sync" → "Error de conexión"
- Emojis en banners 2FA y seguridad limpiados
- Toggle de contraseña: emoji 👁️/🙈 → ícono SVG

### 5. Limpieza visual general

- **Sidebar footer:** "NIVEL 1" + "⭐ pts" → "PROGRESO" + "X puntos" — menos gamey, mismo dato.
- **Loading screens:** Emoji 💸 reemplazado por logo Sky real en App.jsx, AuthScreen, OnboardingScreen.
- **Mr. Money avatar fallback:** Emoji 💸 → SVG persona ícono profesional.
- **Mensajes iniciales:** Sin emoji 💼, tono directo y profesional.

---

## Instalación

1. Copiar `src/` al directorio `frontend/src/` del proyecto (reemplaza archivos existentes)
2. Copiar `public/assets/banks/*.png` a `frontend/public/assets/banks/`
3. Los logos se sirven desde `/assets/banks/` vía Vite estático

**No se modificó:** backend, servicios, API, lógica de negocio, ni datos.  
**Compatibilidad:** Drop-in replacement. Mismos props, mismos imports, misma API.

---

## Qué NO se cambió (y por qué)

- **Emojis en categorías** (🍔 🚌 etc.) — Son reconocibles y consistentes. Un upgrade a SVG icons es válido pero requiere un sprite sheet o librería de íconos. Recomendado para v2.
- **Emojis en toasts de gamificación** (🏆 🎉) — Son micro-feedback estándar en apps modernas (Duolingo, banking apps). No transmiten "demo".
- **Estructura de tabs** — Mr. Money como panel flotante es el siguiente step natural, pero requiere refactoring del layout. Recomendado para siguiente iteración.
