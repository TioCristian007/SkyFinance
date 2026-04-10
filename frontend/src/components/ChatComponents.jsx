// components/ChatComponents.jsx
import { C } from "../data/colors.js";

// Mr. Money avatar — usa la imagen real si está disponible, fallback a emoji
function MrMoneyAvatar({ size = 32 }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%",
      background: `linear-gradient(135deg,${C.green},${C.greenDark})`,
      display: "flex", alignItems: "center", justifyContent: "center",
      flexShrink: 0, overflow: "hidden",
      boxShadow: "0 2px 8px rgba(0,200,83,0.3)",
    }}>
      <img
        src="/mr-money.png"
        alt="Mr. Money"
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
        onError={(e) => {
          e.target.style.display = "none";
          e.target.nextSibling.style.display = "flex";
        }}
      />
      <span style={{ display: "none", fontSize: size * 0.44, alignItems: "center", justifyContent: "center", width: "100%", height: "100%" }}>
        💸
      </span>
    </div>
  );
}

function renderBold(t) {
  return t.split(/\*\*(.*?)\*\*/g).map((p, i) =>
    i % 2 === 1 ? <strong key={i}>{p}</strong> : p
  );
}

export function ChatBubble({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div style={{
      display: "flex", justifyContent: isUser ? "flex-end" : "flex-start",
      marginBottom: 4, animation: "fadeUp 0.25s ease",
    }}>
      {!isUser && (
        <div style={{ marginRight: 8, alignSelf: "flex-end" }}>
          <MrMoneyAvatar size={32} />
        </div>
      )}
      <div style={{
        maxWidth: "78%", padding: "10px 14px",
        borderRadius: isUser ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
        background: isUser ? `linear-gradient(135deg,${C.green},${C.greenDark})` : C.white,
        color: isUser ? C.white : C.textPrimary,
        fontSize: 13.5, lineHeight: 1.6,
        border: isUser ? "none" : `1px solid ${C.border}`,
        whiteSpace: "pre-wrap",
      }}>
        {msg.text.split("\n").map((line, i, arr) => (
          <span key={i}>{renderBold(line)}{i < arr.length - 1 && <br />}</span>
        ))}
        <div style={{ fontSize: 10, opacity: 0.55, marginTop: 4, textAlign: "right" }}>
          {msg.time}
        </div>
      </div>
    </div>
  );
}

export function TypingDots() {
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
      <MrMoneyAvatar size={32} />
      <div style={{
        display: "flex", gap: 5, padding: "10px 14px",
        background: C.white, borderRadius: "16px 16px 16px 4px",
        width: "fit-content", border: `1px solid ${C.border}`,
      }}>
        {[0, 1, 2].map((i) => (
          <span key={i} style={{
            width: 7, height: 7, borderRadius: "50%", background: C.green,
            display: "block", animation: "bounce 1.2s infinite",
            animationDelay: `${i * 0.2}s`,
          }} />
        ))}
      </div>
    </div>
  );
}

export function XPBar({ points }) {
  const level = Math.floor(points / 100) + 1;
  const pct   = points % 100;
  return (
    <div style={{
      background: "rgba(255,255,255,0.08)", borderRadius: 14,
      padding: "10px 14px", border: "1px solid rgba(255,255,255,0.08)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 15 }}>⭐</span>
          <span style={{ fontSize: 13, fontWeight: 700, color: C.white }}>Nivel {level}</span>
        </div>
        <span style={{ fontSize: 12, color: "rgba(255,255,255,0.55)", fontFamily: "monospace" }}>
          {points} pts
        </span>
      </div>
      <div style={{ height: 6, background: "rgba(255,255,255,0.12)", borderRadius: 99, overflow: "hidden" }}>
        <div style={{
          height: "100%", width: `${pct}%`,
          background: `linear-gradient(90deg,${C.gold},#FF8F00)`,
          borderRadius: 99, transition: "width 0.6s ease",
        }} />
      </div>
      <div style={{ fontSize: 10, color: "rgba(255,255,255,0.4)", marginTop: 4, textAlign: "right" }}>
        {100 - pct} pts para nivel {level + 1}
      </div>
    </div>
  );
}