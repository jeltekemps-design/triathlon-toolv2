const state = {
  auth: null, // {user, pass}
  planned: [],
  strength: [],
  activities: [],
  wellness: [],
  syncLogs: [],
};

// ---------- Auth ----------

function authHeader() {
  return "Basic " + btoa(`${state.auth.user}:${state.auth.pass}`);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: {
      "Authorization": authHeader(),
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
  });
  if (res.status === 401) throw new Error("unauthorized");
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

async function tryLogin(user, pass) {
  state.auth = { user, pass };
  await api("/api/sync-logs"); // cheap authenticated endpoint to validate creds
  localStorage.setItem("tt_auth", JSON.stringify(state.auth));
}

function initAuth() {
  const saved = localStorage.getItem("tt_auth");
  if (saved) {
    state.auth = JSON.parse(saved);
    showApp();
    loadEverything();
  } else {
    showLogin();
  }
}

function showLogin() {
  document.getElementById("login-screen").classList.remove("hidden");
  document.getElementById("app").classList.add("hidden");
}

function showApp() {
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
}

document.getElementById("login-btn").addEventListener("click", async () => {
  const user = document.getElementById("login-user").value.trim();
  const pass = document.getElementById("login-pass").value;
  const errEl = document.getElementById("login-error");
  errEl.textContent = "";
  try {
    await tryLogin(user, pass);
    showApp();
    loadEverything();
  } catch (e) {
    errEl.textContent = "Invalid credentials, or the server isn't reachable.";
  }
});

document.getElementById("logout-btn").addEventListener("click", () => {
  localStorage.removeItem("tt_auth");
  state.auth = null;
  showLogin();
});

// ---------- Tabs ----------

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(s => s.classList.add("hidden"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.remove("hidden");
    if (btn.dataset.tab === "insights") renderInsights();
  });
});

// ---------- Data loading ----------

async function loadEverything() {
  try {
    const [planned, strength, activities, wellness, syncLogs] = await Promise.all([
      api("/api/planned-workouts?days=14"),
      api("/api/strength-sessions?days=14"),
      api("/api/activities?days=30"),
      api("/api/wellness?days=30"),
      api("/api/sync-logs"),
    ]);
    state.planned = planned;
    state.strength = strength;
    state.activities = activities;
    state.wellness = wellness;
    state.syncLogs = syncLogs;
    renderSyncStatus();
    renderToday();
    renderWeek();
  } catch (e) {
    if (e.message === "unauthorized") {
      localStorage.removeItem("tt_auth");
      showLogin();
    } else {
      console.error(e);
    }
  }
}

function renderSyncStatus() {
  const el = document.getElementById("sync-status");
  if (!state.syncLogs.length) { el.textContent = "No syncs yet"; return; }
  const last = state.syncLogs[0];
  const when = last.finished_at ? new Date(last.finished_at).toLocaleString() : "running…";
  el.textContent = `Last sync (${last.source}): ${last.status} — ${when}`;
}

document.getElementById("sync-now-btn").addEventListener("click", async () => {
  const btn = document.getElementById("sync-now-btn");
  btn.disabled = true;
  btn.textContent = "Syncing…";
  try {
    await api("/api/sync/garmin", { method: "POST" });
    await api("/api/sync/trainingpeaks", { method: "POST" }).catch(() => {});
    await loadEverything();
  } finally {
    btn.disabled = false;
    btn.textContent = "Sync now";
  }
});

// ---------- Today ----------

function isoToday() {
  return new Date().toISOString().slice(0, 10);
}

function renderToday() {
  const today = isoToday();
  const container = document.getElementById("tab-today");
  const workouts = state.planned.filter(w => w.date === today);
  const strength = state.strength.filter(s => s.date === today);

  container.innerHTML = `
    <div class="card">
      <h2>Endurance — ${today}</h2>
      ${workouts.length ? workouts.map(workoutItemHtml).join("") : "<p class='hint'>Nothing scheduled today.</p>"}
    </div>
    <div class="card">
      <h2>Strength / core</h2>
      ${strength.length ? strength.map(strengthItemHtml).join("") : "<p class='hint'>No strength session today.</p>"}
    </div>
  `;
  attachCheckboxHandlers(container);
}

function workoutItemHtml(w) {
  return `
    <div class="workout-item ${w.completed ? "completed" : ""}">
      <div class="checkbox-row">
        <input type="checkbox" data-kind="workout" data-id="${w.id}" ${w.completed ? "checked" : ""}>
        <div>
          <span class="sport-badge">${w.sport || "other"}</span><strong>${escapeHtml(w.title || "Workout")}</strong>
          <span class="meta">${w.description ? escapeHtml(w.description) : ""}
            ${w.planned_duration_sec ? Math.round(w.planned_duration_sec / 60) + " min" : ""}
            ${w.planned_tss ? " · TSS " + w.planned_tss : ""}
            ${w.source ? " · via " + w.source : ""}</span>
        </div>
      </div>
    </div>`;
}

function strengthItemHtml(s) {
  const exercises = (s.exercises || []).map(e => `${e.name} — ${e.prescription}`).join("; ");
  return `
    <div class="strength-item ${s.completed ? "completed" : ""}">
      <div class="checkbox-row">
        <input type="checkbox" data-kind="strength" data-id="${s.id}" ${s.completed ? "checked" : ""}>
        <div>
          <span class="sport-badge">${s.focus || "strength"}</span><strong>${s.duration_min || "?"} min</strong>
          <span class="meta">${escapeHtml(exercises)}</span>
          ${s.rationale ? `<span class="meta">Why: ${escapeHtml(s.rationale)}</span>` : ""}
        </div>
      </div>
    </div>`;
}

function attachCheckboxHandlers(container) {
  container.querySelectorAll('input[type=checkbox]').forEach(cb => {
    cb.addEventListener("change", async () => {
      const kind = cb.dataset.kind;
      const id = cb.dataset.id;
      const path = kind === "workout"
        ? `/api/planned-workouts/${id}/complete`
        : `/api/strength-sessions/${id}/complete`;
      await api(path, { method: "PATCH", body: JSON.stringify({ completed: cb.checked }) });
      await loadEverything();
    });
  });
}

// ---------- Week ----------

function renderWeek() {
  const container = document.getElementById("week-columns");
  const today = new Date();
  const monday = new Date(today);
  monday.setDate(today.getDate() - ((today.getDay() + 6) % 7));

  let html = "";
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    const iso = d.toISOString().slice(0, 10);
    const isToday = iso === isoToday();
    const dayWorkouts = state.planned.filter(w => w.date === iso);
    const dayStrength = state.strength.filter(s => s.date === iso);
    html += `
      <div class="day-col ${isToday ? "today" : ""}">
        <h3>${d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</h3>
        ${dayWorkouts.map(workoutItemHtml).join("")}
        ${dayStrength.map(strengthItemHtml).join("")}
        ${(!dayWorkouts.length && !dayStrength.length) ? "<p class='hint'>Rest</p>" : ""}
      </div>`;
  }
  container.innerHTML = html;
  attachCheckboxHandlers(container);
}

// ---------- Insights ----------

let loadChart, recoveryChart;

function renderInsights() {
  const wellness = [...state.wellness].sort((a, b) => a.date.localeCompare(b.date));
  const labels = wellness.map(w => w.date.slice(5));

  const loadByDate = {};
  state.activities.forEach(a => {
    loadByDate[a.date] = (loadByDate[a.date] || 0) + (a.perceived_load || 0);
  });
  const loadSeries = wellness.map(w => loadByDate[w.date] || 0);

  const loadCtx = document.getElementById("chart-load");
  if (loadChart) loadChart.destroy();
  loadChart = new Chart(loadCtx, {
    type: "bar",
    data: { labels, datasets: [{ label: "Daily training load", data: loadSeries, backgroundColor: "#3fb6a8" }] },
    options: { responsive: true, plugins: { legend: { display: false } } },
  });

  const recoveryCtx = document.getElementById("chart-recovery");
  if (recoveryChart) recoveryChart.destroy();
  recoveryChart = new Chart(recoveryCtx, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Sleep score", data: wellness.map(w => w.sleep_score), borderColor: "#3fb6a8", tension: 0.3 },
        { label: "Body battery (low)", data: wellness.map(w => w.body_battery_low), borderColor: "#f2a154", tension: 0.3 },
        { label: "Resting HR", data: wellness.map(w => w.resting_hr), borderColor: "#e2685f", tension: 0.3 },
      ],
    },
    options: { responsive: true },
  });

  const total = state.planned.length;
  const done = state.planned.filter(w => w.completed).length;
  const sTotal = state.strength.length;
  const sDone = state.strength.filter(s => s.completed).length;
  document.getElementById("completion-stats").innerHTML = `
    <p>Endurance: ${done}/${total} completed</p>
    <p>Strength: ${sDone}/${sTotal} completed</p>
  `;
}

// ---------- Add / Import ----------

document.getElementById("manual-workout-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  await api("/api/planned-workouts", {
    method: "POST",
    body: JSON.stringify({
      date: form.get("date"),
      sport: form.get("sport"),
      title: form.get("title"),
      description: form.get("description"),
      planned_duration_sec: form.get("duration_min") ? Number(form.get("duration_min")) * 60 : null,
      planned_tss: form.get("tss") ? Number(form.get("tss")) : null,
    }),
  });
  e.target.reset();
  await loadEverything();
});

document.getElementById("ics-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  document.getElementById("ics-text").value = await file.text();
});

document.getElementById("ics-import-btn").addEventListener("click", async () => {
  const text = document.getElementById("ics-text").value;
  const result = await api("/api/planned-workouts/import-ics", {
    method: "POST",
    body: JSON.stringify({ ics_text: text }),
  });
  document.getElementById("ics-result").textContent = `Imported ${result.imported} workout(s).`;
  await loadEverything();
});

document.getElementById("generate-strength-btn").addEventListener("click", async () => {
  const weekStart = document.getElementById("strength-week-start").value || mondayIso();
  const raceDate = document.getElementById("strength-race-date").value || null;
  const result = await api("/api/strength-plan/generate", {
    method: "POST",
    body: JSON.stringify({ week_start: weekStart, race_date: raceDate }),
  });
  document.getElementById("strength-gen-result").textContent = `Generated ${result.length} session(s) for the week.`;
  await loadEverything();
});

function mondayIso() {
  const today = new Date();
  const monday = new Date(today);
  monday.setDate(today.getDate() - ((today.getDay() + 6) % 7));
  return monday.toISOString().slice(0, 10);
}

function escapeHtml(str) {
  if (!str) return "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ---------- Init ----------
initAuth();
