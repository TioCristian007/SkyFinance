import { getAdminClient } from "./supabaseClient.js";

const db = () => getAdminClient();

export async function getProfile(userId) {
  if (!userId) return null;
  const { data, error } = await db().from("profiles").select("*").eq("id", userId).single();
  if (error) { console.error("[db] getProfile:", error.message); return null; }
  return data;
}

export async function upsertProfile(userId, updates) {
  if (!userId) return null;
  const { data, error } = await db()
    .from("profiles")
    .upsert({ id: userId, ...updates, updated_at: new Date().toISOString() })
    .select().single();
  if (error) { console.error("[db] upsertProfile:", error.message); return null; }
  return data;
}

export async function getTransactions(userId) {
  if (!userId) return [];
  const { data, error } = await db()
    .from("transactions").select("*").eq("user_id", userId)
    .order("date", { ascending: false });
  if (error) { console.error("[db] getTransactions:", error.message); return []; }
  return data || [];
}

export async function insertTransaction(userId, tx) {
  if (!userId) return null;
  // Campos bancarios opcionales — cuando el caller viene del sync bancario
  // o quiere reconciliar a mano una movimiento externo, preservamos la
  // trazabilidad al bank_account_id y el external_id para dedupe futuro.
  const row = {
    user_id:     userId,
    amount:      tx.amount,
    category:    tx.category,
    description: tx.desc || tx.description,
    date:        tx.date || new Date().toISOString().split("T")[0],
  };
  if (tx.bank_account_id || tx.bankAccountId) row.bank_account_id = tx.bank_account_id || tx.bankAccountId;
  if (tx.external_id     || tx.externalId)    row.external_id     = tx.external_id     || tx.externalId;
  if (tx.movement_source || tx.movementSource) row.movement_source = tx.movement_source || tx.movementSource;

  const { data, error } = await db()
    .from("transactions")
    .insert(row)
    .select().single();
  if (error) { console.error("[db] insertTransaction:", error.message); return null; }
  return { ...data, desc: data.description };
}

export async function removeTransaction(userId, txId) {
  if (!userId) return false;
  const { error } = await db()
    .from("transactions").delete().eq("id", txId).eq("user_id", userId);
  if (error) { console.error("[db] removeTransaction:", error.message); return false; }
  return true;
}

export async function getGoals(userId) {
  if (!userId) return [];
  const { data, error } = await db()
    .from("goals").select("*").eq("user_id", userId)
    .order("created_at", { ascending: false });
  if (error) { console.error("[db] getGoals:", error.message); return []; }
  return (data || []).map(g => ({ ...g, targetAmount: g.target_amount, savedAmount: g.saved_amount }));
}

export async function insertGoal(userId, goal) {
  if (!userId) return null;
  const { data, error } = await db()
    .from("goals")
    .insert({
      user_id:       userId,
      title:         goal.title,
      target_amount: goal.targetAmount,
      saved_amount:  goal.savedAmount || 0,
      deadline:      goal.deadline || null,
      icon:          goal.icon || "🎯",
      type:          goal.type || "secundaria",
    })
    .select().single();
  if (error) { console.error("[db] insertGoal:", error.message); return null; }
  return { ...data, targetAmount: data.target_amount, savedAmount: data.saved_amount };
}

export async function patchGoal(userId, goalId, updates) {
  if (!userId) return null;
  const dbUpdates = {};
  if (updates.savedAmount !== undefined) dbUpdates.saved_amount = updates.savedAmount;
  if (updates.title !== undefined)       dbUpdates.title = updates.title;
  dbUpdates.updated_at = new Date().toISOString();
  const { data, error } = await db()
    .from("goals").update(dbUpdates)
    .eq("id", goalId).eq("user_id", userId)
    .select().single();
  if (error) { console.error("[db] patchGoal:", error.message); return null; }
  return { ...data, targetAmount: data.target_amount, savedAmount: data.saved_amount };
}

export async function removeGoal(userId, goalId) {
  if (!userId) return false;
  const { error } = await db()
    .from("goals").delete().eq("id", goalId).eq("user_id", userId);
  if (error) { console.error("[db] removeGoal:", error.message); return false; }
  return true;
}

export async function getChallengeStates(userId) {
  if (!userId) return [];
  const { data, error } = await db()
    .from("challenge_states").select("*").eq("user_id", userId);
  if (error) { console.error("[db] getChallengeStates:", error.message); return []; }
  return data || [];
}

export async function insertChallengeState(userId, challengeId) {
  if (!userId) return null;
  const { data, error } = await db()
    .from("challenge_states")
    .insert({ user_id: userId, challenge_id: challengeId, status: "active" })
    .select().single();
  if (error) { console.error("[db] insertChallengeState:", error.message); return null; }
  return data;
}

export async function completeChallengeState(userId, challengeId, pointsEarned) {
  if (!userId) return false;
  const { error } = await db()
    .from("challenge_states")
    .update({
      status:        "completed",
      completed_at:  new Date().toISOString().split("T")[0],
      points_earned: pointsEarned,
    })
    .eq("user_id", userId).eq("challenge_id", challengeId);
  if (error) { console.error("[db] completeChallengeState:", error.message); return false; }
  return true;
}

export async function addPoints(userId, points) {
  if (!userId) return;
  const profile = await getProfile(userId);
  if (!profile) return;
  const { error } = await db()
    .from("profiles")
    .update({ points: (profile.points || 0) + points })
    .eq("id", userId);
  if (error) console.error("[db] addPoints:", error.message);
}

export async function getEarnedBadges(userId) {
  if (!userId) return [];
  const { data, error } = await db()
    .from("earned_badges").select("badge_id").eq("user_id", userId);
  if (error) { console.error("[db] getEarnedBadges:", error.message); return []; }
  return (data || []).map(b => b.badge_id);
}

export async function insertBadge(userId, badgeId) {
  if (!userId) return;
  const { error } = await db()
    .from("earned_badges")
    .insert({ user_id: userId, badge_id: badgeId });
  if (error && !error.message.includes("unique")) {
    console.error("[db] insertBadge:", error.message);
  }
}