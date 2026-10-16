/**
 * RGCDC Debate Tournament Tabulation System
 * REST API Client Bridge for FastAPI Backend Synchronization
 */

const API_BASE_URL = window.RGCDC_API_URL || "http://localhost:8000/api";

export async function fetchTournamentOverview() {
  const res = await fetch(`${API_BASE_URL}/tournament`);
  if (!res.ok) throw new Error("Failed to load tournament overview");
  return res.json();
}

export async function updateTournamentFormat(format, name = "3rd RGCDC Dialogues 2026") {
  const res = await fetch(`${API_BASE_URL}/tournament/format`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      host_institution: "Rangpur Government College Debating Club (RGCDC)",
      format,
      total_prelim_rounds: 5,
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function registerTeamAPI(payload) {
  const res = await fetch(`${API_BASE_URL}/teams`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function registerAdjudicatorAPI(payload) {
  const res = await fetch(`${API_BASE_URL}/adjudicators`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateRoundDrawAPI(roundNumber) {
  const res = await fetch(`${API_BASE_URL}/rounds/draw?round_number=${roundNumber}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function submitBallotAPI(payload) {
  const res = await fetch(`${API_BASE_URL}/ballots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function submitJudgeEvaluationAPI(payload) {
  const res = await fetch(`${API_BASE_URL}/evaluations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
