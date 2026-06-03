// ============================================================================
// CONFIG
// ============================================================================
const SUPABASE_URL = 'https://wokpofioebqiqedgliux.supabase.co';
const SUPABASE_KEY = 'sb_publishable_H9ANeb9duo0IONfcWsQloA_pH_eNUIV';
const sb = supabase.createClient(SUPABASE_URL, SUPABASE_KEY);

const STATUSES = ['Backlog','Discovery','In Progress','In Review','Live','On Hold','Cancelled'];

// ============================================================================
// STATE
// ============================================================================
let session     = null;
let profile     = null;     // { id, display_name, role }
let projects    = [];       // all rows from ai_projects
let signoffs    = [];       // all rows from ai_signoffs
let audit       = {};       // project_id -> [audit rows]
let editingId   = null;     // currently-edited project id, or null = new
let signoffPid  = null;     // project being signed off
let loadError   = null;     // last fetch error message, or null

let filterState = {
  search: '', theme: '', status: '', owner: '', priority: '', preset: '', mine: false,
  sortBy: 'score', sortDir: 'desc',
};

// ============================================================================
// HELPERS
// ============================================================================
function escapeHTML(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function pillClass(status) { return 'pill pill-' + (status || '').replace(/\s/g,''); }
function scoreClass(score) { return score >= 13 ? 'high' : score >= 9 ? 'med' : 'low'; }
// A deliverable can be a web link OR a file path (incl. an Excel workbook on
// OneDrive / a local drive). Turn a Windows path into a file:// link so it opens.
function deliverableHref(url) {
  if (!url) return '';
  if (/^[A-Za-z]:[\\/]/.test(url)) return 'file:///' + url.replace(/\\/g, '/');
  if (/^\\\\/.test(url))           return 'file:' + url.replace(/\\/g, '/'); // UNC share
  return url;
}
// Label the link by what it points to, so an Excel deliverable doesn't read "View live project".
function deliverableLabel(url) {
  const u = (url || '').toLowerCase();
  if (/\.(xlsx?|csv|ods)(\?|#|$)/.test(u))        return 'Open spreadsheet';
  if (/\.(docx?|pdf|pptx?|txt|md)(\?|#|$)/.test(u)) return 'Open document';
  if (/^[a-z]:[\\/]|^\\\\/.test(u))                return 'Open file';
  return 'View live project';
}
// --- Inline line-icons (lucide-style). ic('name') -> <svg> string. ---
const ICONS = {
  grid:    '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
  clock:   '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  inbox:   '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  check:   '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  alert:   '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  table:   '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>',
  flag:    '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22V4"/>',
  plus:    '<path d="M12 5v14M5 12h14"/>',
  download:'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
  reset:   '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  logout:  '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
  search:  '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  eye:     '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  pause:   '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
  xcircle: '<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/>',
  circle:  '<circle cx="12" cy="12" r="8"/>',
  chart:   '<path d="M3 3v18h18"/><rect x="7" y="11" width="3" height="7"/><rect x="12" y="7" width="3" height="11"/><rect x="17" y="4" width="3" height="14"/>',
  moon:    '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>',
  sun:     '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  clock2:  '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  sparkle: '<path d="M12 3l1.7 4.8L18.5 9.5l-4.8 1.7L12 16l-1.7-4.8L5.5 9.5l4.8-1.7z"/><path d="M5 15l.9 2.1L8 18l-2.1.9L5 21l-.9-2.1L2 18l2.1-.9z"/>',
};
function ic(name, cls) {
  const body = ICONS[name];
  if (!body) return '';
  return `<svg class="ic${cls ? ' ' + cls : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}
const STATUS_ICON = {
  'Backlog': 'circle', 'Discovery': 'search', 'In Progress': 'clock',
  'In Review': 'eye', 'Live': 'check', 'On Hold': 'pause', 'Cancelled': 'xcircle',
};
function statusPill(status) {
  return `<span class="${pillClass(status)} pill-icon">${ic(STATUS_ICON[status] || 'circle')}${escapeHTML(status)}</span>`;
}

// --- Owner avatars (deterministic color from name) ---
function avatarColor(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return `hsl(${h % 360} 42% 42%)`;
}
function initials(name) {
  return name.trim().split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase();
}
function ownerAvatars(owners) {
  if (!owners || !owners.length) return '<span style="color:var(--fg-faint)">unassigned</span>';
  const dots = owners.map(o => `<span class="avatar" style="background:${avatarColor(o)}" title="${escapeHTML(o)}">${escapeHTML(initials(o))}</span>`).join('');
  return `<div class="owners">${dots}<span class="owner-names">${escapeHTML(owners.join(', '))}</span></div>`;
}

// --- Theme color-coding ---
const THEME_COLOR = {
  'Foundation': '#2d4a73',
  'Sales — Rep Tools': '#1f6a47',
  'Sales — Pipeline & Renewal': '#0f766e',
  'Marketing': '#9a3412',
  'Lead Gen': '#7a5310',
  'Design & Layout': '#6d28d9',
  'Operations': '#1d4ed8',
  'Finance': '#b45309',
};
function themeColor(t) { return THEME_COLOR[t] || '#64748b'; }

function isAdmin() { return profile && profile.role === 'admin'; }
// A target is "overdue" only if it's in the past AND the project isn't done/dropped.
function isOverdue(p) {
  if (!p.target_date || p.status === 'Live' || p.status === 'Cancelled') return false;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  return new Date(p.target_date + 'T00:00:00') < today;
}
// "Stale" = no update in 30+ days and not done/dropped — surfaces neglected projects.
function isStale(p) {
  if (!p.updated_at || p.status === 'Live' || p.status === 'Cancelled') return false;
  return (Date.now() - new Date(p.updated_at).getTime()) > 30 * 86400000;
}
function formatDate(s) {
  if (!s) return '';
  const d = new Date(s + (s.length === 10 ? 'T12:00:00' : ''));
  return isNaN(d) ? s : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}
function formatWhen(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}
function renderRiskFlags(arr) {
  if (!arr || !arr.length) return '';
  return arr.map(flag => {
    const cls = flag === 'High Blast Radius' ? 'chip chip-danger'
              : (flag === 'Strategic Alignment' || flag === 'External Data Dependency') ? 'chip chip-warn'
              : 'chip';
    return `<span class="${cls}">${escapeHTML(flag)}</span>`;
  }).join('');
}
function parseCSV(s) {
  return (s || '').split(',').map(x => x.trim()).filter(Boolean);
}

// ============================================================================
// AUTH
// ============================================================================
function applyTheme(mode) {
  const dark = mode === 'dark';
  document.documentElement.dataset.theme = dark ? 'dark' : '';
  const item = document.getElementById('um-theme');
  if (item) item.innerHTML = ic(dark ? 'sun' : 'moon') + (dark ? 'Light mode' : 'Dark mode');
}
function toggleTheme() {
  const next = (localStorage.getItem('thm_theme') === 'dark') ? 'light' : 'dark';
  try { localStorage.setItem('thm_theme', next); } catch (_) {}
  applyTheme(next);
  if (currentView === 'insights') renderInsights();  // recolor charts for the new theme
}

async function init() {
  applyTheme(localStorage.getItem('thm_theme'));
  const { data } = await sb.auth.getSession();
  session = data.session;
  if (!session) {
    document.getElementById('login-screen').style.display = 'flex';
    return;
  }
  await loadProfile();
  await mountApp();
}

async function loadProfile() {
  const { data, error } = await sb.from('profiles').select('*').eq('id', session.user.id).single();
  if (error || !data) {
    profile = { id: session.user.id, display_name: session.user.email, role: 'viewer' };
  } else {
    profile = data;
  }
}

function showMsg(kind, text) {
  const msg = document.getElementById('login-msg');
  msg.className = 'login-msg ' + kind;
  msg.textContent = text;
  msg.style.display = 'block';
}

// Shared temporary password new staff use for their very first sign-in.
const DEFAULT_TEMP_PW = 'THMnew2026!';

// PASSWORD LOGIN (also bootstraps first-time accounts via the temp password)
document.getElementById('password-form').addEventListener('submit', async e => {
  e.preventDefault();
  const email = document.getElementById('pw-email').value.trim();
  const password = document.getElementById('pw-password').value;
  const btn = document.getElementById('pw-btn');
  btn.disabled = true;
  document.getElementById('login-msg').style.display = 'none';

  let { error, data } = await sb.auth.signInWithPassword({ email, password });

  // First time: signing in with the shared temp password creates the account.
  // The DB trigger enforces @thmmedia.com; we also gate here for a clean message.
  if (error && password === DEFAULT_TEMP_PW && /@thmmedia\.com$/i.test(email)) {
    const up = await sb.auth.signUp({ email, password });
    if (up.error) {
      btn.disabled = false;
      const m = up.error.message || '';
      showMsg('err', /already registered|already exists/i.test(m)
        ? 'This account already exists — sign in with your own password, not the temporary one.'
        : m);
      return;
    }
    if (!up.data.session) {
      // "Confirm email" is ON in Supabase — they must confirm before first login.
      btn.disabled = false;
      showMsg('ok', 'Account created! Check your email to confirm it, then sign in with the temporary password.');
      return;
    }
    data = up.data; error = null;
  }

  btn.disabled = false;
  if (error) { showMsg('err', error.message); return; }
  session = data.session;
  document.getElementById('login-screen').style.display = 'none';
  await loadProfile();
  await mountApp();
});

document.getElementById('um-signout').addEventListener('click', async () => {
  await sb.auth.signOut();
  location.reload();
});

// Note: we deliberately don't trigger reload from onAuthStateChange — the
// password / OTP forms call mountApp() directly after sign-in, and the magic
// link redirect path is handled by init() reading the URL hash via getSession().

// ============================================================================
// FIRST-LOGIN PASSWORD SETUP
// ============================================================================
function openPasswordSetup() {
  document.getElementById('ps-pw').value = '';
  document.getElementById('ps-pw2').value = '';
  document.getElementById('password-err').style.display = 'none';
  openModal(document.getElementById('password-modal'));
}
async function savePasswordSetup(e) {
  e.preventDefault();
  const pw  = document.getElementById('ps-pw').value;
  const pw2 = document.getElementById('ps-pw2').value;
  const err = document.getElementById('password-err');
  if (pw.length < 8)        { err.textContent = 'Password must be at least 8 characters.'; err.style.display = 'block'; return; }
  if (pw === DEFAULT_TEMP_PW){ err.textContent = 'Please choose a password different from the temporary one.'; err.style.display = 'block'; return; }
  if (pw !== pw2)           { err.textContent = 'Those passwords don\'t match.'; err.style.display = 'block'; return; }
  const { error } = await sb.auth.updateUser({ password: pw });
  if (error) { err.textContent = error.message; err.style.display = 'block'; return; }
  await sb.rpc('mark_password_set');
  if (profile) profile.password_set = true;
  dismissModal(document.getElementById('password-modal'));
  showToast('Password set — you\'re all set!');
}

// ============================================================================
// DATA LOADING
// ============================================================================
async function mountApp() {
  document.getElementById('app').style.display = 'block';
  document.getElementById('user-name').textContent = `${profile.display_name} (${profile.role})`;
  const admin = isAdmin();
  if (admin) {
    document.getElementById('new-project-btn').style.display = 'inline-block';
    document.getElementById('new-decision-btn').style.display = 'inline-block';
    document.getElementById('um-activity').hidden = false;
    document.getElementById('um-ask').hidden = false;
  } else {
    // Intake-only: hide the Projects + Decisions tabs and show a welcome.
    document.getElementById('viewer-banner').style.display = 'block';
    document.querySelectorAll('.viewtab').forEach(t => { if (t.dataset.view !== 'intake') t.style.display = 'none'; });
  }
  renderSkeleton();
  await Promise.all([fetchProjects(), fetchSignoffs(), fetchIntake(), fetchDecisions()]);
  loadFilters();
  const urlOpenId = readURL();   // URL overrides saved filters/tab for shareable links
  populateFilters();
  applyFilterUI();
  attachEvents();
  render();
  renderIntake();
  renderDecisions();
  showView(admin ? currentView : 'intake');   // honor ?v= (admins) / force intake (viewers)
  subscribeRealtime();
  // Deep link to a specific project (?p=ID)
  if (admin && urlOpenId) {
    setTimeout(() => {
      const row = document.querySelector(`.main-row[data-id="${urlOpenId}"]`);
      const ex = document.querySelector(`.expandable-row[data-for="${urlOpenId}"]`);
      if (row) { deepOpenId = urlOpenId; row.scrollIntoView({ block: 'center' }); if (ex) { ex.classList.add('open'); row.setAttribute('aria-expanded', 'true'); } }
    }, 80);
  }
  // First-time users: prompt to set a password (admins already have password_set=true).
  if (profile && profile.password_set === false) openPasswordSetup();
}

async function fetchProjects() {
  const { data, error } = await sb.from('ai_projects').select('*').order('score', { ascending: false });
  if (error) { console.error(error); loadError = error.message; projects = []; return; }
  loadError = null;
  projects = data;
}

async function fetchSignoffs() {
  const { data, error } = await sb.from('ai_signoffs').select('*').order('signed_at', { ascending: false });
  if (error) { console.error(error); showToast("Couldn't load sign-offs", 'err'); return; }
  signoffs = data;
}

async function fetchAudit(projectId) {
  if (audit[projectId]) return audit[projectId];
  const { data, error } = await sb.from('ai_project_audit')
    .select('*').eq('project_id', projectId)
    .order('changed_at', { ascending: false }).limit(25);
  if (error) { console.error(error); return []; }
  audit[projectId] = data;
  return data;
}

// ============================================================================
// REALTIME
// ============================================================================
function subscribeRealtime() {
  sb.channel('ai_projects_changes')
    .on('postgres_changes', { event: '*', schema: 'public', table: 'ai_projects' }, payload => {
      if (payload.eventType === 'INSERT') projects.push(payload.new);
      else if (payload.eventType === 'UPDATE') {
        const i = projects.findIndex(p => p.id === payload.new.id);
        if (i >= 0) projects[i] = payload.new;
        delete audit[payload.new.id];   // invalidate audit cache for this project
      }
      else if (payload.eventType === 'DELETE') {
        projects = projects.filter(p => p.id !== payload.old.id);
      }
      populateFilters();   // a new/removed project may add/drop a theme or owner
      render();
    })
    .on('postgres_changes', { event: '*', schema: 'public', table: 'ai_signoffs' }, async () => {
      await fetchSignoffs();
      render();
    })
    .on('postgres_changes', { event: '*', schema: 'public', table: 'ai_intake_submissions' }, async () => {
      await fetchIntake();
      renderIntake();
    })
    .on('postgres_changes', { event: '*', schema: 'public', table: 'ai_decisions' }, async () => {
      await fetchDecisions();
      renderDecisions();
    })
    .subscribe();
}

// ============================================================================
// RENDER
// ============================================================================
// KPI presets group several statuses (or compute "needs attention") into one
// click, so people don't have to know the exact status vocabulary.
function presetMatch(preset, p) {
  switch (preset) {
    case 'live':       return p.status === 'Live';
    case 'inprogress': return p.status === 'In Progress' || p.status === 'In Review';
    case 'queued':     return p.status === 'Backlog' || p.status === 'Discovery';
    case 'attention':  return isOverdue(p) || (p.priority === 'High' && p.status !== 'Live' && p.status !== 'Cancelled');
    default:           return true;
  }
}

function filterProjects() {
  return projects.filter(p => {
    if (filterState.preset && !presetMatch(filterState.preset, p)) return false;
    if (filterState.mine) {
      const me = (profile?.display_name || '').toLowerCase();
      if (!(p.owners || []).some(o => o.toLowerCase() === me)) return false;
    }
    if (filterState.theme    && p.theme !== filterState.theme)   return false;
    if (filterState.status   && p.status !== filterState.status) return false;
    if (filterState.owner    && !(p.owners || []).includes(filterState.owner)) return false;
    if (filterState.priority && p.priority !== filterState.priority) return false;
    if (filterState.search) {
      const q = filterState.search.toLowerCase();
      const hay = [
        p.project_name, p.theme, (p.owners||[]).join(' '),
        p.priority, p.description, p.success_metric, (p.risk_flags||[]).join(' '), p.notes
      ].join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  }).sort((a, b) => {
    const dir = filterState.sortDir === 'desc' ? -1 : 1;
    if (filterState.sortBy === 'priority') {
      const rank = { 'High': 3, 'Medium': 2, 'Low': 1 };
      return ((rank[a.priority] || 0) - (rank[b.priority] || 0)) * dir;
    }
    let av = a[filterState.sortBy], bv = b[filterState.sortBy];
    if (Array.isArray(av)) av = av.join(',');
    if (Array.isArray(bv)) bv = bv.join(',');
    av = av ?? ''; bv = bv ?? '';
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
    return String(av).localeCompare(String(bv)) * dir;
  });
}

function renderKPIs() {
  const live   = projects.filter(p => p.status === 'Live').length;
  const inProg = projects.filter(p => p.status === 'In Progress' || p.status === 'In Review').length;
  const queued = projects.filter(p => p.status === 'Backlog' || p.status === 'Discovery').length;
  const attn   = projects.filter(p => isOverdue(p) || (p.priority === 'High' && p.status !== 'Live' && p.status !== 'Cancelled')).length;
  const tiles = [
    { key: '',           label: 'All projects',    n: projects.length, tone: 'total',    ico: 'grid' },
    { key: 'inprogress', label: 'In progress',     n: inProg,          tone: 'progress', ico: 'clock' },
    { key: 'queued',     label: 'In the queue',    n: queued,          tone: 'queue',    ico: 'inbox' },
    { key: 'live',       label: 'Live',            n: live,            tone: 'live',     ico: 'check' },
    { key: 'attention',  label: 'Needs attention', n: attn,            tone: 'attn',     ico: 'alert' },
  ];
  const noFilters = !filterState.preset && !filterState.status;
  const kpis = document.getElementById('kpis');
  kpis.innerHTML = tiles.map(t => {
    const active = (t.key && t.key === filterState.preset) || (t.key === '' && noFilters) ? 'active' : '';
    const alert = (t.key === 'attention' && t.n > 0) ? ' data-alert="1"' : '';
    return `<div class="kpi ${active}" data-preset="${t.key}" data-tone="${t.tone}"${alert}><span class="kpi-ic">${ic(t.ico)}</span><span class="num" data-count="${t.n}">${t.n}</span><span class="label">${escapeHTML(t.label)}</span></div>`;
  }).join('');
  kpis.querySelectorAll('.kpi').forEach(el => {
    el.addEventListener('click', () => {
      const key = el.dataset.preset;
      filterState.preset = (key && filterState.preset === key) ? '' : key;
      // a preset owns the status dropdown — clear it so they don't conflict
      filterState.status = '';
      document.getElementById('status-filter').value = '';
      saveFilters();
      render();
    });
  });
  document.getElementById('header-meta').textContent =
    `${projects.length} projects · ${live} live · ${inProg} in progress`;
  if (!kpisAnimated && projects.length) { animateCounts(); kpisAnimated = true; }
}

function signoffsFor(pid) {
  return signoffs.filter(s => s.project_id === pid);
}

function renderTable() {
  const tbody = document.getElementById('projects-body');
  const filtered = filterProjects();
  document.getElementById('result-count').textContent = `${filtered.length} of ${projects.length} projects`;

  if (loadError) {
    tbody.innerHTML = `<tr><td colspan="6" class="table-empty error">Couldn't load projects — ${escapeHTML(loadError)}<br><span class="table-empty-sub">Try refreshing. If it persists, your account may not have access yet.</span></td></tr>`;
    return;
  }
  if (!filtered.length) {
    const filtered0 = projects.length > 0;
    const msg = filtered0 ? 'No projects match the current filters.' : 'No projects in the registry yet.';
    tbody.innerHTML = `<tr><td colspan="6" class="table-empty"><span class="empty-ic">${ic(filtered0 ? 'search' : 'inbox')}</span><div>${msg}</div></td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(p => {
    const overdue = isOverdue(p);
    const target = p.target_date
      ? `<span class="${overdue ? 'target-overdue' : ''}">${formatDate(p.target_date)}${overdue ? '<span class="overdue-tag">overdue</span>' : ''}</span>`
      : '<span style="color:var(--fg-faint)">—</span>';
    const ownerTxt = ownerAvatars(p.owners);
    const pct = Math.round((p.progress || 0) * 100);
    const sos = signoffsFor(p.id);
    const sosBlock = sos.length
      ? `<div class="signoffs">${sos.map(s => `<span class="signoff">✓ ${escapeHTML(s.signed_by_name)} (${s.role}) · ${formatWhen(s.signed_at)}</span>`).join('')}</div>`
      : '';
    const priorityCell =
      (p.priority ? `<span class="pill pill-priority-${p.priority}">${escapeHTML(p.priority)}</span>` : '') +
      `<div class="priority-score" title="Priority score = Impact + Ease + Strategic Fit, each rated 1–5">${p.score}/15</div>`;
    const deliverableBlock = p.deliverable_url
      ? `<div><a class="deliverable-link" href="${escapeHTML(deliverableHref(p.deliverable_url))}" target="_blank" rel="noopener noreferrer">${deliverableLabel(p.deliverable_url)}</a></div>`
      : '';
    const notesBlock = p.notes
      ? `<div class="notes-block">
           <div class="field-label">Notes / Open Questions</div>
           <div class="notes-body">${escapeHTML(p.notes)}</div>
         </div>`
      : '';
    const rowMarkers =
      (p.deliverable_url ? ` <span class="row-marker deliv" title="${escapeHTML(deliverableLabel(p.deliverable_url))}">↗</span>` : '') +
      (sos.length ? ` <span class="row-marker signed" title="Signed off (${sos.length})">✓</span>` : '') +
      (isStale(p) ? ` <span class="row-marker stale" title="No updates in 30+ days">💤</span>` : '');
    return `
      <tr data-id="${p.id}" class="main-row" tabindex="0" aria-expanded="false">
        <td class="project-name" style="box-shadow: inset 3px 0 0 ${themeColor(p.theme)}">
          <div class="project-line"><span class="caret" aria-hidden="true">›</span>${escapeHTML(p.project_name)}${rowMarkers}</div>
          ${p.theme ? `<div class="project-theme" style="color:${themeColor(p.theme)}">${escapeHTML(p.theme)}</div>` : ''}
        </td>
        <td class="status-cell"${isAdmin() ? ' title="Click to change status"' : ''}>${statusPill(p.status)}</td>
        <td class="owner-cell"${isAdmin() ? ' title="Click to set owners"' : ''}>${ownerTxt}</td>
        <td class="progress-cell"${isAdmin() ? ' title="Click to set progress"' : ''}>
          <div class="progress"><div class="progress-bar" style="width:${pct}%"></div></div>
          <div class="progress-text">${pct}%</div>
        </td>
        <td class="target-cell"${isAdmin() ? ' title="Click to set target date"' : ''}>${target}</td>
        <td class="priority-cell"${isAdmin() ? ' title="Click to set priority"' : ''}>${priorityCell}</td>
      </tr>
      <tr class="expandable-row" data-for="${p.id}">
        <td colspan="6"><div class="exp-inner">
          <div class="desc">${escapeHTML(p.description || '—')}</div>
          ${deliverableBlock}
          <div class="grid">
            <div><div class="field-label">Priority</div><div class="field-value">${p.priority ? `<span class="pill pill-priority-${p.priority}">${escapeHTML(p.priority)}</span>` : '—'}</div></div>
            <div><div class="field-label">Owner</div><div class="field-value">${(p.owners && p.owners.length) ? escapeHTML(p.owners.join(', ')) : '—'}</div></div>
            <div><div class="field-label">Target</div><div class="field-value">${p.target_date ? formatDate(p.target_date) : '—'}</div></div>
            <div><div class="field-label">Success Metric</div><div class="field-value">${escapeHTML(p.success_metric || '—')}</div></div>
            <div><div class="field-label">Risk Flags</div><div class="field-value">${renderRiskFlags(p.risk_flags) || '—'}</div></div>
            <div><div class="field-label">Updated</div><div class="field-value">${formatWhen(p.updated_at)}</div></div>
          </div>
          ${notesBlock}
          ${sosBlock}
          ${isAdmin() ? `
            <div class="row-actions">
              <button data-action="edit"    data-id="${p.id}">Edit</button>
              <button data-action="signoff" data-id="${p.id}" class="secondary">Sign off</button>
              <button data-action="history" data-id="${p.id}" class="secondary">View history</button>
            </div>` : `
            <div class="row-actions">
              <button data-action="history" data-id="${p.id}" class="secondary">View history</button>
            </div>`}
          <div class="audit" data-audit-for="${p.id}" style="display:none">
            <h4>Recent changes</h4>
            <div class="entries">Loading…</div>
          </div>
        </div></td>
      </tr>`;
  }).join('');

  tbody.querySelectorAll('.main-row').forEach(row => {
    const toggle = () => {
      const ex = tbody.querySelector(`.expandable-row[data-for="${row.dataset.id}"]`);
      if (ex) row.setAttribute('aria-expanded', ex.classList.toggle('open') ? 'true' : 'false');
    };
    row.addEventListener('click', e => {
      if (e.target.closest('button') || e.target.closest('.status-cell') || e.target.closest('.owner-cell')
        || e.target.closest('.progress-cell') || e.target.closest('.target-cell') || e.target.closest('.priority-cell')) return;
      toggle();
    });
    row.addEventListener('keydown', e => {
      if (e.target.closest('button')) return;
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
    if (isAdmin()) {
      const sc = row.querySelector('.status-cell');
      if (sc) sc.addEventListener('click', e => { e.stopPropagation(); openStatusMenu(row.dataset.id, sc.querySelector('.pill') || sc); });
      const pc = row.querySelector('.progress-cell');
      if (pc) pc.addEventListener('click', e => { e.stopPropagation(); openProgressMenu(row.dataset.id, pc); });
      const oc = row.querySelector('.owner-cell');
      if (oc) oc.addEventListener('click', e => { e.stopPropagation(); openOwnerMenu(row.dataset.id, oc); });
      const tc = row.querySelector('.target-cell');
      if (tc) tc.addEventListener('click', e => { e.stopPropagation(); openDateMenu(row.dataset.id, tc); });
      const prc = row.querySelector('.priority-cell');
      if (prc) prc.addEventListener('click', e => { e.stopPropagation(); openPriorityMenu(row.dataset.id, prc); });
    }
  });

  tbody.querySelectorAll('button[data-action]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const id = btn.dataset.id;
      const action = btn.dataset.action;
      if (action === 'edit')    openProjectModal(id);
      if (action === 'signoff') openSignoffModal(id);
      if (action === 'history') toggleHistory(id);
    });
  });
}

async function toggleHistory(pid) {
  const box = document.querySelector(`[data-audit-for="${pid}"]`);
  if (!box) return;
  if (box.style.display === 'none') {
    box.style.display = 'block';
    const entries = box.querySelector('.entries');
    entries.textContent = 'Loading…';
    const rows = await fetchAudit(pid);
    if (!rows.length) {
      entries.innerHTML = '<div class="entry" style="color:var(--fg-faint)">No changes recorded yet.</div>';
    } else {
      entries.innerHTML = rows.map(r => `
        <div class="entry">
          <strong>${escapeHTML(r.changed_by_name || 'unknown')}</strong>
          changed <strong>${escapeHTML(r.field_name)}</strong>:
          ${escapeHTML(r.old_value ?? '—')} → ${escapeHTML(r.new_value ?? '—')}
          <span class="when">${formatWhen(r.changed_at)}</span>
        </div>`).join('');
    }
  } else {
    box.style.display = 'none';
  }
}

function render() {
  renderKPIs();
  renderPipeline();
  renderTable();
}

// Inline status editing: click a status pill in the table to pick a new status.
function closeStatusMenu() { const m = document.getElementById('status-menu'); if (m) m.remove(); }
function openStatusMenu(id, anchor) {
  closeAllInlineMenus();
  const p = projects.find(x => x.id === id);
  if (!p) return;
  const menu = document.createElement('div');
  menu.className = 'status-menu';
  menu.id = 'status-menu';
  menu.innerHTML = STATUSES.map(s =>
    `<button type="button" class="sm-item ${s === p.status ? 'cur' : ''}" data-s="${escapeHTML(s)}">${ic(STATUS_ICON[s] || 'circle')}<span>${escapeHTML(s)}</span></button>`
  ).join('');
  document.body.appendChild(menu);
  const r = anchor.getBoundingClientRect();
  menu.style.top = (r.bottom + window.scrollY + 4) + 'px';
  menu.style.left = (r.left + window.scrollX) + 'px';
  menu.querySelectorAll('.sm-item').forEach(b => b.addEventListener('click', async e => {
    e.stopPropagation();
    const ns = b.dataset.s;
    closeStatusMenu();
    if (ns === p.status) return;
    const prev = p.status;
    const wentLive = ns === 'Live' && prev !== 'Live';
    p.status = ns;                 // optimistic
    render();
    const { error } = await sb.from('ai_projects').update({ status: ns, updated_by: profile.id }).eq('id', id);
    if (error) { p.status = prev; render(); showToast("Couldn't update status", 'err'); return; }
    showToast(wentLive ? '🎉 ' + p.project_name + ' is now live!' : 'Status updated');
    if (wentLive) fireConfetti();
  }));
  // close on next outside click / escape
  setTimeout(() => {
    document.addEventListener('click', closeStatusMenu, { once: true });
    document.addEventListener('keydown', function esc(ev) { if (ev.key === 'Escape') { closeStatusMenu(); document.removeEventListener('keydown', esc); } });
  }, 0);
}

// Inline progress editing: click a progress bar in the table to drag a slider.
function closeProgressMenu() { const m = document.getElementById('progress-menu'); if (m) m.remove(); }
function openProgressMenu(id, anchor) {
  closeAllInlineMenus();
  const p = projects.find(x => x.id === id);
  if (!p) return;
  const cur = Math.round((p.progress || 0) * 100);
  const menu = document.createElement('div');
  menu.className = 'progress-menu';
  menu.id = 'progress-menu';
  menu.innerHTML = `<div class="pm-head"><span class="pm-label">Progress</span><span class="pm-val"><span id="pm-num">${cur}</span>%</span></div>
    <input id="pm-range" type="range" min="0" max="100" step="5" value="${cur}" aria-label="Progress percent">`;
  document.body.appendChild(menu);
  const r = anchor.getBoundingClientRect();
  menu.style.top = (r.bottom + window.scrollY + 6) + 'px';
  menu.style.left = (r.left + window.scrollX) + 'px';
  menu.addEventListener('mousedown', e => e.stopPropagation());
  menu.addEventListener('click', e => e.stopPropagation());
  const range = menu.querySelector('#pm-range');
  const num = menu.querySelector('#pm-num');
  range.addEventListener('input', () => { num.textContent = range.value; });
  range.addEventListener('change', async () => {
    const val = Number(range.value);
    closeProgressMenu();
    if (val === cur) return;
    const prev = p.progress;
    p.progress = val / 100;          // optimistic
    render();
    const { error } = await sb.from('ai_projects').update({ progress: val / 100, updated_by: profile.id }).eq('id', id);
    if (error) { p.progress = prev; render(); showToast("Couldn't update progress", 'err'); return; }
    showToast(`Progress set to ${val}%`);
  });
  setTimeout(() => {
    document.addEventListener('click', closeProgressMenu, { once: true });
    document.addEventListener('keydown', function esc(ev) { if (ev.key === 'Escape') { closeProgressMenu(); document.removeEventListener('keydown', esc); } });
  }, 0);
  setTimeout(() => range.focus(), 10);
}

// Position a popover just below an anchor cell.
function positionMenu(menu, anchor) {
  const r = anchor.getBoundingClientRect();
  menu.style.top = (r.bottom + window.scrollY + 6) + 'px';
  menu.style.left = (r.left + window.scrollX) + 'px';
}
function closeInlineOnOutside(closeFn) {
  setTimeout(() => {
    document.addEventListener('click', closeFn, { once: true });
    document.addEventListener('keydown', function esc(ev) { if (ev.key === 'Escape') { closeFn(); document.removeEventListener('keydown', esc); } });
  }, 0);
}

// Inline owner editing: click the owner cell to toggle owners from a dropdown.
function closeOwnerMenu() { const m = document.getElementById('owner-menu'); if (m) m.remove(); }
function openOwnerMenu(id, anchor) {
  closeAllInlineMenus();
  const p = projects.find(x => x.id === id);
  if (!p) return;
  const candidates = [...new Set(projects.flatMap(x => x.owners || []).filter(Boolean))].sort();
  const menu = document.createElement('div');
  menu.className = 'inline-menu owner-menu';
  menu.id = 'owner-menu';
  const items = candidates.length
    ? candidates.map(o => {
        const on = (p.owners || []).includes(o);
        return `<button type="button" class="om-item ${on ? 'cur' : ''}" data-o="${escapeHTML(o)}">${ic(on ? 'check' : 'circle')}<span>${escapeHTML(o)}</span></button>`;
      }).join('')
    : '<div class="im-empty">No owners yet — add one via Edit.</div>';
  menu.innerHTML = `<div class="im-label">Owners</div>${items}`;
  document.body.appendChild(menu);
  positionMenu(menu, anchor);
  menu.addEventListener('mousedown', e => e.stopPropagation());
  menu.addEventListener('click', e => e.stopPropagation());
  menu.querySelectorAll('.om-item').forEach(b => b.addEventListener('click', async () => {
    const name = b.dataset.o;
    const set = new Set(p.owners || []);
    set.has(name) ? set.delete(name) : set.add(name);
    const next = [...set];
    const prev = p.owners;
    p.owners = next;
    const nowOn = set.has(name);
    b.classList.toggle('cur', nowOn);
    const svg = b.querySelector('.ic'); if (svg) svg.remove();
    b.insertAdjacentHTML('afterbegin', ic(nowOn ? 'check' : 'circle'));
    render();
    const { error } = await sb.from('ai_projects').update({ owners: next, updated_by: profile.id }).eq('id', id);
    if (error) { p.owners = prev; render(); showToast("Couldn't update owners", 'err'); }
  }));
  closeInlineOnOutside(closeOwnerMenu);
}

// Inline target-date editing: click the target cell to pick a date.
function closeDateMenu() { const m = document.getElementById('date-menu'); if (m) m.remove(); }
function openDateMenu(id, anchor) {
  closeAllInlineMenus();
  const p = projects.find(x => x.id === id);
  if (!p) return;
  const menu = document.createElement('div');
  menu.className = 'inline-menu date-menu';
  menu.id = 'date-menu';
  menu.innerHTML = `<div class="im-label">Target date</div>
    <input id="dm-date" type="date" value="${p.target_date || ''}">
    <button type="button" class="im-clear" id="dm-clear">Clear date</button>`;
  document.body.appendChild(menu);
  positionMenu(menu, anchor);
  menu.addEventListener('mousedown', e => e.stopPropagation());
  menu.addEventListener('click', e => e.stopPropagation());
  const input = menu.querySelector('#dm-date');
  const commit = async (val) => {
    closeDateMenu();
    if ((val || '') === (p.target_date || '')) return;
    const prev = p.target_date;
    p.target_date = val || null;
    render();
    const { error } = await sb.from('ai_projects').update({ target_date: val || null, updated_by: profile.id }).eq('id', id);
    if (error) { p.target_date = prev; render(); showToast("Couldn't update target", 'err'); return; }
    showToast(val ? 'Target set to ' + formatDate(val) : 'Target cleared');
  };
  input.addEventListener('change', () => commit(input.value));
  menu.querySelector('#dm-clear').addEventListener('click', () => commit(''));
  closeInlineOnOutside(closeDateMenu);
  setTimeout(() => { input.focus(); if (input.showPicker) { try { input.showPicker(); } catch (_) {} } }, 10);
}

function closeAllInlineMenus() {
  ['status-menu', 'progress-menu', 'owner-menu', 'date-menu', 'priority-menu']
    .forEach(id => { const m = document.getElementById(id); if (m) m.remove(); });
}

// Inline priority editing: click the priority cell to set High / Medium / Low / none.
function closePriorityMenu() { const m = document.getElementById('priority-menu'); if (m) m.remove(); }
function openPriorityMenu(id, anchor) {
  closeAllInlineMenus();
  const p = projects.find(x => x.id === id);
  if (!p) return;
  const opts = [{ v: 'High' }, { v: 'Medium' }, { v: 'Low' }, { v: '', label: 'None' }];
  const menu = document.createElement('div');
  menu.className = 'inline-menu priority-menu';
  menu.id = 'priority-menu';
  menu.innerHTML = `<div class="im-label">Priority</div>` + opts.map(o => {
    const cur = (p.priority || '') === o.v;
    const dot = o.v ? `<span class="pri-dot" data-p="${o.v}"></span>` : `<span class="pri-dot none"></span>`;
    return `<button type="button" class="om-item ${cur ? 'cur' : ''}" data-v="${o.v}">${dot}<span>${o.label || o.v}</span></button>`;
  }).join('');
  document.body.appendChild(menu);
  positionMenu(menu, anchor);
  menu.addEventListener('mousedown', e => e.stopPropagation());
  menu.addEventListener('click', e => e.stopPropagation());
  menu.querySelectorAll('.om-item').forEach(b => b.addEventListener('click', async () => {
    const v = b.dataset.v;
    closePriorityMenu();
    if ((p.priority || '') === v) return;
    const prev = p.priority;
    p.priority = v || null;
    render();
    const { error } = await sb.from('ai_projects').update({ priority: v || null, updated_by: profile.id }).eq('id', id);
    if (error) { p.priority = prev; render(); showToast("Couldn't update priority", 'err'); return; }
    showToast(v ? 'Priority set to ' + v : 'Priority cleared');
  }));
  closeInlineOnOutside(closePriorityMenu);
}

// Shimmer placeholder rows while the first fetch is in flight.
function renderSkeleton(rows = 6) {
  const tbody = document.getElementById('projects-body');
  if (!tbody) return;
  tbody.innerHTML = Array.from({ length: rows }, () => `
    <tr class="skel-row">
      <td><span class="skel" style="width:60%"></span><span class="skel" style="width:34%;margin-top:6px"></span></td>
      <td><span class="skel skel-pill"></span></td>
      <td><span class="skel" style="width:68%"></span></td>
      <td><span class="skel" style="width:80px"></span></td>
      <td><span class="skel" style="width:54%"></span></td>
      <td><span class="skel skel-pill"></span></td>
    </tr>`).join('');
}

// One-time count-up on the KPI numbers.
let kpisAnimated = false;
function animateCounts() {
  document.querySelectorAll('#kpis .num').forEach(el => {
    const target = parseInt(el.dataset.count, 10) || 0;
    if (target <= 0) { el.textContent = '0'; return; }
    const dur = 650; let start = null;
    el.textContent = '0';
    const step = ts => {
      if (start === null) start = ts;
      const p = Math.min((ts - start) / dur, 1);
      el.textContent = Math.round(p * target);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

// Load a CDN script once, on demand (keeps initial page load light).
const _scriptPromises = {};
function loadScript(src) {
  if (_scriptPromises[src]) return _scriptPromises[src];
  _scriptPromises[src] = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src; s.onload = resolve; s.onerror = reject;
    document.head.appendChild(s);
  });
  return _scriptPromises[src];
}
const ensureConfetti = () => loadScript('https://cdn.jsdelivr.net/npm/canvas-confetti@1');

// Celebratory burst when a project ships (loads the lib on first use).
async function fireConfetti() {
  if (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  try { await ensureConfetti(); } catch (_) { return; }
  if (typeof confetti !== 'function') return;
  confetti({ particleCount: 130, spread: 75, origin: { y: 0.6 }, colors: ['#1f6a47', '#2d4a73', '#a87a26', '#6d28d9'] });
}

// Slide-in toast notifications. Optional action = { label, fn } renders a button (e.g. Undo).
function showToast(msg, kind = 'ok', action) {
  const wrap = document.getElementById('toasts');
  if (!wrap) return;
  const el = document.createElement('div');
  el.className = 'toast toast-' + kind;
  el.innerHTML = ic(kind === 'ok' ? 'check' : 'alert') + `<span>${escapeHTML(msg)}</span>`;
  let life = 3200;
  if (action) {
    life = 6000;
    const b = document.createElement('button');
    b.className = 'toast-action';
    b.textContent = action.label;
    b.addEventListener('click', () => { action.fn(); el.classList.remove('show'); setTimeout(() => el.remove(), 200); });
    el.appendChild(b);
  }
  wrap.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 260); }, life);
}

// Insights — rendered when the tab opens.
// Plain-English insights: a row of headline numbers + a by-theme bar breakdown.
function renderInsights() {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const ym = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0');
  const live = s => s === 'Live', dead = s => s === 'Cancelled';
  const active = projects.filter(p => p.status !== 'On Hold' && !dead(p.status));
  const launching = projects.filter(p => p.target_date && p.target_date.slice(0, 7) === ym && !live(p.status) && !dead(p.status));
  const attention = projects.filter(p => isOverdue(p) || (p.priority === 'High' && !live(p.status) && !dead(p.status)));
  const unowned = projects.filter(p => (!p.owners || !p.owners.length) && !dead(p.status));
  const inFlight = active.filter(p => !live(p.status));
  const avg = inFlight.length ? Math.round(inFlight.reduce((s, p) => s + (p.progress || 0), 0) / inFlight.length * 100) : 0;

  const stats = [
    { n: active.length,    label: 'Active',                tone: 'total' },
    { n: launching.length, label: 'Launching this month',  tone: 'progress' },
    { n: attention.length, label: 'Needs attention',       tone: 'attn',  alert: attention.length > 0 },
    { n: unowned.length,   label: 'Unowned',               tone: 'queue', alert: unowned.length > 0 },
    { n: avg + '%',        label: 'Avg progress',          tone: 'live' },
  ];
  document.getElementById('insight-stats').innerHTML = stats.map(s =>
    `<div class="stat-card" data-tone="${s.tone}"${s.alert ? ' data-alert="1"' : ''}><span class="stat-num">${s.n}</span><span class="stat-label">${escapeHTML(s.label)}</span></div>`
  ).join('');

  const counts = {};
  projects.forEach(p => { if (p.theme) counts[p.theme] = (counts[p.theme] || 0) + 1; });
  const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max = rows.length ? rows[0][1] : 1;
  document.getElementById('theme-bars').innerHTML = rows.length
    ? rows.map(([t, n]) =>
        `<div class="bar-row"><span class="bar-label">${escapeHTML(t)}</span><span class="bar-track"><span class="bar-fill" style="width:${(n / max * 100).toFixed(0)}%;background:${themeColor(t)}"></span></span><span class="bar-count">${n}</span></div>`
      ).join('')
    : '<div class="act-empty">No projects yet.</div>';
}

// Slim stacked status bar under the KPIs — shows the whole pipeline at a glance.
function renderPipeline() {
  const wrap = document.getElementById('pipeline');
  if (!wrap) return;
  const c = s => projects.filter(p => p.status === s).length;
  const segs = [
    { label: 'Queued',      preset: 'queued',      n: c('Backlog') + c('Discovery'), color: 'var(--status-backlog-fg)' },
    { label: 'In progress', status: 'In Progress', n: c('In Progress'),              color: 'var(--status-progress-fg)' },
    { label: 'In review',   status: 'In Review',   n: c('In Review'),                color: 'var(--status-review-fg)' },
    { label: 'Live',        status: 'Live',        n: c('Live'),                     color: 'var(--status-live-fg)' },
    { label: 'On hold',     status: 'On Hold',     n: c('On Hold'),                  color: 'var(--status-hold-fg)' },
    { label: 'Cancelled',   status: 'Cancelled',   n: c('Cancelled'),                color: 'var(--status-cancelled-fg)' },
  ].filter(s => s.n > 0);
  const total = segs.reduce((a, s) => a + s.n, 0);
  if (!total) { wrap.innerHTML = ''; return; }
  const isActive = s => s.preset ? filterState.preset === s.preset : (filterState.status === s.status && !filterState.preset);
  wrap.innerHTML =
    `<div class="pipeline" role="img" aria-label="Projects by stage">` +
      segs.map((s, i) => `<div class="pipe-seg ${isActive(s) ? 'active' : ''}" data-pi="${i}" style="width:${(s.n / total * 100).toFixed(2)}%;background:${s.color}" title="${escapeHTML(s.label)}: ${s.n} — click to filter"></div>`).join('') +
    `</div>` +
    `<div class="pipe-legend">` +
      segs.map((s, i) => `<button type="button" class="pipe-leg ${isActive(s) ? 'active' : ''}" data-pi="${i}"><span class="dot" style="background:${s.color}"></span>${escapeHTML(s.label)} <strong>${s.n}</strong></button>`).join('') +
    `</div>`;
  const applySeg = i => {
    const s = segs[i];
    if (s.preset) { filterState.preset = filterState.preset === s.preset ? '' : s.preset; filterState.status = ''; }
    else { filterState.status = filterState.status === s.status ? '' : s.status; filterState.preset = ''; }
    document.getElementById('status-filter').value = filterState.status;
    saveFilters();
    render();
  };
  wrap.querySelectorAll('[data-pi]').forEach(el => el.addEventListener('click', () => applySeg(+el.dataset.pi)));
}

// --- Filter persistence (localStorage) so a refresh keeps your view ---
const FILTER_KEY = 'thm_ai_filters_v1';
function saveFilters() {
  try { localStorage.setItem(FILTER_KEY, JSON.stringify(filterState)); } catch (_) {}
  writeURL();
}

// --- Shareable deep-linked URL: reflects tab + filters (+ open project) ---
let deepOpenId = null;
function writeURL() {
  const pr = new URLSearchParams();
  if (currentView && currentView !== 'projects') pr.set('v', currentView);
  const f = filterState;
  if (f.search)   pr.set('q', f.search);
  if (f.theme)    pr.set('theme', f.theme);
  if (f.status)   pr.set('status', f.status);
  if (f.owner)    pr.set('owner', f.owner);
  if (f.priority) pr.set('priority', f.priority);
  if (f.preset)   pr.set('preset', f.preset);
  if (f.mine)     pr.set('mine', '1');
  if (deepOpenId) pr.set('p', deepOpenId);
  const qs = pr.toString();
  history.replaceState(null, '', qs ? '?' + qs : location.pathname);
}
function readURL() {
  const pr = new URLSearchParams(location.search);
  if (pr.get('v')) currentView = pr.get('v');
  const f = filterState;
  f.search   = pr.get('q') || f.search;
  f.theme    = pr.get('theme') || f.theme;
  f.status   = pr.get('status') || f.status;
  f.owner    = pr.get('owner') || f.owner;
  f.priority = pr.get('priority') || f.priority;
  f.preset   = pr.get('preset') || f.preset;
  if (pr.get('mine') === '1') f.mine = true;
  return pr.get('p');
}
function loadFilters() {
  try {
    const s = JSON.parse(localStorage.getItem(FILTER_KEY) || 'null');
    if (s && typeof s === 'object') filterState = { ...filterState, ...s };
  } catch (_) {}
}
function applyFilterUI() {
  document.getElementById('search').value = filterState.search || '';
  ['theme', 'status', 'owner', 'priority'].forEach(k => {
    const el = document.getElementById(k + '-filter');
    if (!el) return;
    el.value = filterState[k] || '';
    if (el.value !== (filterState[k] || '')) filterState[k] = '';   // saved option no longer exists
  });
  document.getElementById('mine-toggle').classList.toggle('active', !!filterState.mine);
}

function updateSortIndicators() {
  document.querySelectorAll('th[data-sort]').forEach(t => {
    t.innerHTML = t.textContent.replace(/[▲▼]/g, '').trim();
    if (t.dataset.sort === filterState.sortBy) {
      t.innerHTML += ` <span class="sort-indicator">${filterState.sortDir === 'desc' ? '▼' : '▲'}</span>`;
      t.setAttribute('aria-sort', filterState.sortDir === 'desc' ? 'descending' : 'ascending');
    } else {
      t.removeAttribute('aria-sort');
    }
  });
}
function applySort(key) {
  if (filterState.sortBy === key) filterState.sortDir = filterState.sortDir === 'asc' ? 'desc' : 'asc';
  else { filterState.sortBy = key; filterState.sortDir = ['progress', 'score'].includes(key) ? 'desc' : 'asc'; }
  updateSortIndicators();
  saveFilters();
  renderTable();
}

// ============================================================================
// FILTERS
// ============================================================================
// Idempotent: rebuilds option lists from current data and preserves the active
// selection, so it's safe to call again after a realtime insert/delete.
function populateFilters() {
  const themes = [...new Set(projects.map(p => p.theme).filter(Boolean))].sort();
  const owners = [...new Set(projects.flatMap(p => p.owners || []).filter(Boolean))].sort();
  const fill = (sel, values, base) => {
    const cur = sel.value;
    sel.innerHTML = base + values.map(v => `<option value="${escapeHTML(v)}">${escapeHTML(v)}</option>`).join('');
    if ([...sel.options].some(o => o.value === cur)) sel.value = cur;
  };
  fill(document.getElementById('theme-filter'),  themes,   '<option value="">All Themes</option>');
  fill(document.getElementById('owner-filter'),  owners,   '<option value="">All Owners</option>');
  fill(document.getElementById('status-filter'), STATUSES, '<option value="">All Statuses</option>');
}

function attachEvents() {
  const setFilter = (key, val) => {
    filterState[key] = val;
    if (key === 'status') filterState.preset = '';  // a manual status pick overrides the KPI preset
    saveFilters();
    render();
  };
  let searchTimer;
  document.getElementById('search').addEventListener('input', e => {
    const v = e.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => setFilter('search', v), 160);
  });
  document.getElementById('theme-filter').addEventListener('change', e => setFilter('theme', e.target.value));
  document.getElementById('status-filter').addEventListener('change', e => setFilter('status', e.target.value));
  document.getElementById('owner-filter').addEventListener('change', e => setFilter('owner', e.target.value));
  document.getElementById('priority-filter').addEventListener('change', e => setFilter('priority', e.target.value));
  document.getElementById('reset-filters').addEventListener('click', () => {
    filterState = { search: '', theme: '', status: '', owner: '', priority: '', preset: '', mine: false, sortBy: 'score', sortDir: 'desc' };
    document.getElementById('search').value = '';
    ['theme','status','owner','priority'].forEach(k => document.getElementById(k + '-filter').value = '');
    document.querySelectorAll('.vt-btn, #mine-toggle').forEach(b => b.classList && b.classList.remove('active'));
    saveFilters();
    updateSortIndicators();
    render();
  });
  document.getElementById('export-csv').addEventListener('click', exportCSV);
  document.getElementById('mine-toggle').addEventListener('click', () => {
    filterState.mine = !filterState.mine;
    document.getElementById('mine-toggle').classList.toggle('active', filterState.mine);
    saveFilters();
    render();
  });
  document.getElementById('new-project-btn').addEventListener('click', () => openProjectModal(null));
  document.querySelectorAll('th[data-sort]').forEach(th => {
    th.addEventListener('click', () => applySort(th.dataset.sort));
    th.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); applySort(th.dataset.sort); }
    });
  });
  updateSortIndicators();   // show the default (score ▼) indicator on load
  document.getElementById('modal-cancel').addEventListener('click', closeProjectModal);
  document.getElementById('modal-delete').addEventListener('click', deleteProject);
  document.getElementById('project-form').addEventListener('submit', saveProject);
  document.getElementById('signoff-cancel').addEventListener('click', closeSignoffModal);
  document.getElementById('signoff-form').addEventListener('submit', saveSignoff);

  // View tabs
  document.querySelectorAll('.viewtab').forEach(t => t.addEventListener('click', () => showView(t.dataset.view)));
  // Intake
  document.getElementById('new-intake-btn').addEventListener('click', openIntakeModal);
  document.getElementById('intake-cancel').addEventListener('click', () => dismissModal(document.getElementById('intake-modal')));
  document.getElementById('intake-form').addEventListener('submit', saveIntake);
  document.getElementById('intake-decision-cancel').addEventListener('click', () => dismissModal(document.getElementById('intake-decision-modal')));
  document.getElementById('intake-decision-form').addEventListener('submit', saveIntakeDecision);
  // Decisions
  document.getElementById('new-decision-btn').addEventListener('click', () => openDecisionModal(null));
  document.getElementById('decision-cancel').addEventListener('click', () => dismissModal(document.getElementById('decision-modal')));
  document.getElementById('decision-form').addEventListener('submit', e => { e.preventDefault(); saveDecision(false); });
  document.getElementById('decision-resolve').addEventListener('click', () => saveDecision(true));
  document.getElementById('decision-delete').addEventListener('click', deleteDecision);
  // First-login password setup (required — no skip)
  document.getElementById('password-setup-form').addEventListener('submit', savePasswordSetup);
  // User menu (folds theme / activity / ask / sign-out)
  const userMenu = document.getElementById('user-menu');
  const userMenuBtn = document.getElementById('user-menu-btn');
  const toggleUserMenu = (show) => {
    const open = show ?? userMenu.hidden;
    userMenu.hidden = !open;
    userMenuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  };
  userMenuBtn.addEventListener('click', e => { e.stopPropagation(); toggleUserMenu(); });
  document.addEventListener('click', e => { if (!e.target.closest('.user-menu-wrap')) toggleUserMenu(false); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !userMenu.hidden) toggleUserMenu(false); });
  const menuAction = (id, fn) => document.getElementById(id).addEventListener('click', () => { toggleUserMenu(false); fn(); });
  menuAction('um-theme', toggleTheme);
  menuAction('um-activity', openActivity);
  menuAction('um-ask', openAsk);
  // (um-signout wired at top level)

  document.getElementById('activity-close').addEventListener('click', closeActivity);
  document.getElementById('activity-drawer').addEventListener('mousedown', e => { if (e.target.id === 'activity-drawer') closeActivity(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !document.getElementById('activity-drawer').hidden) closeActivity(); });
  document.getElementById('ask-cancel').addEventListener('click', () => dismissModal(document.getElementById('ask-modal')));
  document.getElementById('ask-form').addEventListener('submit', runAsk);
  document.querySelectorAll('.ask-chip').forEach(c => c.addEventListener('click', () => {
    document.getElementById('ask-q').value = c.textContent;
    runAsk();
  }));

  // Command palette (⌘K / Ctrl-K)
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      document.getElementById('cmdk').hidden ? openCmdk() : closeCmdk();
    }
  });
  const cmdkInput = document.getElementById('cmdk-input');
  cmdkInput.addEventListener('input', e => buildCmdk(e.target.value.trim()));
  cmdkInput.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); cmdkIndex = Math.min(cmdkIndex + 1, cmdkItems.length - 1); updateCmdkSel(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); cmdkIndex = Math.max(cmdkIndex - 1, 0); updateCmdkSel(); }
    else if (e.key === 'Enter') { e.preventDefault(); runCmdk(cmdkItems[cmdkIndex]); }
    else if (e.key === 'Escape') { e.preventDefault(); closeCmdk(); }
  });
  document.getElementById('cmdk').addEventListener('mousedown', e => { if (e.target.id === 'cmdk') closeCmdk(); });

  // Global keyboard shortcuts (admins; ignored while typing or an overlay is open)
  let gPending = false, gTimer;
  document.addEventListener('keydown', e => {
    if (!isAdmin() || e.metaKey || e.ctrlKey || e.altKey) return;
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;
    const overlay = document.querySelector('.modal-backdrop.open') || !document.getElementById('cmdk').hidden
      || !document.getElementById('activity-drawer').hidden || !document.getElementById('user-menu').hidden;
    if (overlay) return;
    if (gPending) {
      const map = { p: 'projects', i: 'intake', d: 'decisions', s: 'insights' };
      if (map[e.key]) { e.preventDefault(); showView(map[e.key]); }
      gPending = false; clearTimeout(gTimer);
      return;
    }
    if (e.key === 'g') { gPending = true; clearTimeout(gTimer); gTimer = setTimeout(() => { gPending = false; }, 800); return; }
    if (e.key === '/') { e.preventDefault(); showView('projects'); document.getElementById('search').focus(); return; }
    if (e.key === 'n') { e.preventDefault(); openProjectModal(null); return; }
  });

  // Decorate tabs + buttons with icons (once)
  const TAB_ICON = { projects: 'table', intake: 'inbox', decisions: 'flag', insights: 'chart' };
  document.querySelectorAll('.viewtab').forEach(t => t.insertAdjacentHTML('afterbegin', ic(TAB_ICON[t.dataset.view] || 'grid')));
  [['new-project-btn','plus'],['new-decision-btn','plus'],['new-intake-btn','plus'],
   ['export-csv','download'],['reset-filters','reset'],
   ['um-ask','sparkle'],['um-activity','clock'],['um-signout','logout']].forEach(([id, name]) => {
    const el = document.getElementById(id); if (el) el.insertAdjacentHTML('afterbegin', ic(name));
  });

  initModals();
}

// ============================================================================
// MODAL PLUMBING (focus, Esc, backdrop-click, scroll-lock) — shared
// ============================================================================
let lastFocused = null;
function openModal(backdrop) {
  lastFocused = document.activeElement;
  backdrop.classList.add('open');
  document.body.style.overflow = 'hidden';
  const first = backdrop.querySelector('input, select, textarea, button');
  if (first) setTimeout(() => first.focus(), 30);
}
function dismissModal(backdrop) {
  backdrop.classList.remove('open');
  if (!document.querySelector('.modal-backdrop.open')) document.body.style.overflow = '';
  if (lastFocused && lastFocused.focus) { try { lastFocused.focus(); } catch (_) {} }
}
function initModals() {
  document.querySelectorAll('.modal-backdrop').forEach(bd => {
    bd.addEventListener('mousedown', e => { if (e.target === bd && !bd.dataset.locked) dismissModal(bd); });
  });
  document.addEventListener('keydown', e => {
    const open = document.querySelector('.modal-backdrop.open');
    if (!open) return;
    if (e.key === 'Escape') { if (!open.dataset.locked) dismissModal(open); return; }
    if (e.key === 'Tab') {
      const f = [...open.querySelectorAll('input, select, textarea, button')]
        .filter(el => !el.disabled && el.offsetParent !== null);
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
}

// ============================================================================
// PROJECT MODAL — new + edit
// ============================================================================
function openProjectModal(id) {
  if (!isAdmin()) return;
  showView('projects');
  editingId = id;
  const p = id ? projects.find(x => x.id === id) : null;
  document.getElementById('modal-title').textContent = id ? 'Edit project' : 'New project';
  document.getElementById('modal-sub').textContent = id
    ? 'Changes save to Supabase and propagate live to anyone viewing.'
    : 'Adds a row to the registry. Visible immediately to everyone.';
  document.getElementById('modal-delete').style.display = id ? 'inline-block' : 'none';

  // Set field values
  const fld = (name, val) => document.getElementById('f-' + name).value = (val ?? '');
  fld('project_name',  p?.project_name);
  fld('theme',         p?.theme || 'Foundation');
  fld('status',        p?.status || 'Backlog');
  fld('owners',        (p?.owners || []).join(', '));
  fld('progress',      p ? Math.round((p.progress || 0) * 100) : '');
  fld('target_date',   p?.target_date || '');
  fld('impact',        p?.impact ?? '');
  fld('ease',          p?.ease ?? '');
  fld('strategic_fit', p?.strategic_fit ?? '');
  fld('priority',      p?.priority || '');
  fld('deliverable_url', p?.deliverable_url || '');
  fld('description',   p?.description);
  fld('success_metric',p?.success_metric);
  fld('risk_flags',    (p?.risk_flags || []).join(', '));
  fld('notes',         p?.notes);
  document.getElementById('modal-err').style.display = 'none';
  openModal(document.getElementById('project-modal'));
}

function closeProjectModal() {
  dismissModal(document.getElementById('project-modal'));
  editingId = null;
}

async function saveProject(e) {
  e.preventDefault();
  const get = id => document.getElementById('f-' + id).value.trim();
  const num = v => v === '' ? null : Number(v);

  const payload = {
    project_name:    get('project_name'),
    theme:           get('theme'),
    status:          get('status'),
    owners:          parseCSV(get('owners')),
    progress:        get('progress') === '' ? 0 : Math.max(0, Math.min(1, Number(get('progress')) / 100)),
    target_date:     get('target_date') || null,
    impact:          num(get('impact')),
    ease:            num(get('ease')),
    strategic_fit:   num(get('strategic_fit')),
    priority:        get('priority') || null,
    deliverable_url: get('deliverable_url') || null,
    description:     get('description') || null,
    success_metric:  get('success_metric') || null,
    risk_flags:      parseCSV(get('risk_flags')),
    notes:           get('notes') || null,
    updated_by:      profile.id,
  };

  const btn = document.getElementById('modal-save');
  const err = document.getElementById('modal-err');
  btn.disabled = true;
  err.style.display = 'none';

  let res;
  if (editingId) {
    res = await sb.from('ai_projects').update(payload).eq('id', editingId);
  } else {
    payload.created_by = profile.id;
    res = await sb.from('ai_projects').insert(payload);
  }

  btn.disabled = false;
  if (res.error) {
    err.textContent = res.error.message;
    err.style.display = 'block';
    return;
  }
  const wasEditing = !!editingId;
  const prev = wasEditing ? projects.find(p => p.id === editingId) : null;
  const wentLive = payload.status === 'Live' && (!prev || prev.status !== 'Live');
  closeProjectModal();
  if (wentLive) { showToast('🎉 ' + payload.project_name + ' is now live!'); fireConfetti(); }
  else showToast(wasEditing ? 'Project updated' : 'Project added');
}

function deleteProject() {
  if (!editingId) return;
  const id = editingId;
  const p = projects.find(x => x.id === id);
  if (!p) return;
  closeProjectModal();
  // Optimistically remove; commit the real delete after a grace period unless undone.
  projects = projects.filter(x => x.id !== id);
  populateFilters();
  render();
  const timer = setTimeout(async () => {
    const { error } = await sb.from('ai_projects').delete().eq('id', id);
    if (error) {
      showToast("Couldn't delete: " + error.message, 'err');
      if (!projects.some(x => x.id === id)) { projects.push(p); populateFilters(); render(); }
    }
  }, 5000);
  showToast(`Deleted "${p.project_name}"`, 'ok', {
    label: 'Undo',
    fn: () => {
      clearTimeout(timer);
      if (!projects.some(x => x.id === id)) { projects.push(p); populateFilters(); render(); }
    },
  });
}

// ============================================================================
// SIGN-OFF MODAL
// ============================================================================
function openSignoffModal(pid) {
  if (!isAdmin()) return;
  signoffPid = pid;
  document.getElementById('s-role').value = profile.display_name.toLowerCase() === 'masen' ? 'masen'
                                          : profile.display_name.toLowerCase() === 'angus' ? 'angus'
                                          : 'other';
  document.getElementById('s-type').value = 'project_ship';
  document.getElementById('s-notes').value = '';
  document.getElementById('signoff-err').style.display = 'none';
  openModal(document.getElementById('signoff-modal'));
}

function closeSignoffModal() {
  dismissModal(document.getElementById('signoff-modal'));
  signoffPid = null;
}

async function saveSignoff(e) {
  e.preventDefault();
  const payload = {
    signoff_type:   document.getElementById('s-type').value,
    project_id:     signoffPid,
    role:           document.getElementById('s-role').value,
    signed_by:      profile.id,
    signed_by_name: profile.display_name,
    notes:          document.getElementById('s-notes').value.trim() || null,
  };
  const { error } = await sb.from('ai_signoffs').insert(payload);
  if (error) {
    const err = document.getElementById('signoff-err');
    err.textContent = error.message;
    err.style.display = 'block';
    return;
  }
  closeSignoffModal();
  showToast('Sign-off recorded');
}

// ============================================================================
// EXPORT
// ============================================================================
function exportCSV() {
  const rows = filterProjects();
  const headers = ['ID','Theme','Project','Status','Owners','Progress %','Target','Priority','Impact','Ease','StratFit','Score','Deliverable URL','Success Metric','Risk Flags','Description','Notes'];
  const lines = [headers.join(',')];
  rows.forEach(p => {
    const row = [
      p.project_number, p.theme, p.project_name, p.status,
      (p.owners || []).join(' + '),
      Math.round((p.progress || 0) * 100),
      p.target_date || '',
      p.priority ?? '',
      p.impact ?? '', p.ease ?? '', p.strategic_fit ?? '', p.score,
      p.deliverable_url ?? '',
      p.success_metric ?? '', (p.risk_flags || []).join(' · '),
      p.description ?? '', p.notes ?? '',
    ];
    lines.push(row.map(v => '"' + String(v ?? '').replace(/"/g,'""') + '"').join(','));
  });
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'thm-ai-projects-' + new Date().toISOString().slice(0,10) + '.csv';
  a.click();
  URL.revokeObjectURL(url);
}

// ============================================================================
// GOVERNANCE — view switching, Intake, Decisions
// ============================================================================
let intake = [];
let decisions = [];
let currentView = 'projects';
let intakeDecisionId = null;
let editingDecisionId = null;

const URGENCY_RANK = { 'Blocking': 0, 'Next Up': 1, 'Soon': 2, 'Eventually': 3 };

function showView(name) {
  currentView = name;
  deepOpenId = null;
  document.querySelectorAll('.viewtab').forEach(t => t.classList.toggle('active', t.dataset.view === name));
  document.getElementById('view-projects').hidden  = name !== 'projects';
  document.getElementById('view-intake').hidden    = name !== 'intake';
  document.getElementById('view-decisions').hidden = name !== 'decisions';
  document.getElementById('view-insights').hidden  = name !== 'insights';
  if (name === 'insights') renderInsights();
  writeURL();
}

// One label/value cell for a card detail grid; renders nothing when empty.
function field(label, val) {
  if (val === null || val === undefined || String(val).trim() === '') return '';
  return `<div><div class="field-label">${escapeHTML(label)}</div><div class="field-value">${escapeHTML(String(val))}</div></div>`;
}

// Expand/collapse + keyboard for the .card rows in a given container.
function wireCards(containerId) {
  document.getElementById(containerId).querySelectorAll('.card-row').forEach(row => {
    const card = row.closest('.card');
    if (!card.dataset.expandable) return;
    const toggle = () => row.setAttribute('aria-expanded', card.classList.toggle('open') ? 'true' : 'false');
    row.addEventListener('click', e => { if (!e.target.closest('button')) toggle(); });
    row.addEventListener('keydown', e => {
      if (e.target.closest('button')) return;
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
  });
}

function setBadge(id, n) {
  const b = document.getElementById(id);
  if (n > 0) { b.hidden = false; b.textContent = n; } else { b.hidden = true; }
}

// ---- Intake ----
async function fetchIntake() {
  const { data, error } = await sb.from('ai_intake_submissions').select('*').order('submitted_at', { ascending: false });
  if (error) { console.error(error); showToast("Couldn't load intake submissions", 'err'); return; }
  intake = data;
}

function renderIntake() {
  const list = document.getElementById('intake-list');
  const pending = intake.filter(s => (s.leadership_decision || 'pending') === 'pending').length;
  document.getElementById('intake-count').textContent = `${intake.length} submission${intake.length !== 1 ? 's' : ''} · ${pending} pending`;
  setBadge('intake-badge', pending);

  if (!intake.length) {
    list.innerHTML = `<div class="card"><div class="card-row" style="cursor:default"><div class="card-main"><div class="card-meta">No submissions yet. Anyone can submit an idea with the button above.</div></div></div></div>`;
    return;
  }
  list.innerHTML = intake.map(s => {
    const dec = s.leadership_decision || 'pending';
    const score = (s.impact || 0) + (s.ease || 0) + (s.strategic_fit || 0);
    return `
    <div class="card" data-expandable="1">
      <div class="card-row" tabindex="0" role="button" aria-expanded="false">
        <div class="card-main">
          <div class="card-title">${escapeHTML(s.project_name)}</div>
          <div class="card-meta">${escapeHTML(s.business_area || 'No theme')} · by ${escapeHTML(s.submitted_by_name)} · ${formatWhen(s.submitted_at)}</div>
        </div>
        <div class="card-side"><span class="pill pill-decision-${escapeHTML(dec)}">${escapeHTML(dec)}</span></div>
      </div>
      <div class="card-detail">
        <div class="grid">
          ${field('Proposed owner', s.proposed_owner)}
          ${field('Problem being solved', s.problem_being_solved)}
          ${field('Why now / strategic fit', s.why_now_strategic_fit)}
          ${field('Success metric', s.success_metric)}
          ${field('Technical approach', s.technical_approach)}
          ${field('Integrations / data sources', s.integrations_data_sources)}
          ${field('Data handled', s.data_handled)}
          ${field('Effort estimate', s.effort_estimate)}
          ${field('Impact / Ease / Fit', `${s.impact ?? '—'} / ${s.ease ?? '—'} / ${s.strategic_fit ?? '—'}  (score ${score}/15)`)}
          ${field('Proposed target', s.proposed_target_date ? formatDate(s.proposed_target_date) : '')}
          ${field('Human-in-the-loop', s.human_in_the_loop)}
          ${field('Rollback plan', s.rollback_plan)}
          ${field('Risk flags', (s.risk_flags || []).join(' · '))}
          ${field('Stakeholders', s.stakeholders)}
          ${field('Open questions', s.open_questions)}
          ${field('Decision', dec + (s.decided_by_name ? ` — ${s.decided_by_name} · ${formatWhen(s.decided_at)}` : ''))}
          ${field('Decision notes', s.decision_notes)}
        </div>
        ${isAdmin() ? `<div class="row-actions"><button data-intake-action="decide" data-id="${s.id}">Record decision</button></div>` : ''}
      </div>
    </div>`;
  }).join('');
  wireCards('intake-list');
  list.querySelectorAll('[data-intake-action="decide"]').forEach(b =>
    b.addEventListener('click', e => { e.stopPropagation(); openIntakeDecision(b.dataset.id); }));
}

function openIntakeModal() {
  ['i-project_name','i-proposed_owner','i-business_area','i-problem_being_solved','i-why_now_strategic_fit',
   'i-success_metric','i-technical_approach','i-integrations_data_sources','i-data_handled','i-effort_estimate',
   'i-proposed_target_date','i-impact','i-ease','i-strategic_fit','i-human_in_the_loop','i-rollback_plan',
   'i-risk_flags','i-stakeholders','i-open_questions'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  document.getElementById('intake-err').style.display = 'none';
  openModal(document.getElementById('intake-modal'));
}

async function saveIntake(e) {
  e.preventDefault();
  const g = id => document.getElementById(id).value.trim();
  const num = id => { const v = document.getElementById(id).value; return v === '' ? null : Number(v); };
  const payload = {
    project_name:              g('i-project_name'),
    proposed_owner:            g('i-proposed_owner') || null,
    business_area:             g('i-business_area') || null,
    problem_being_solved:      g('i-problem_being_solved') || null,
    why_now_strategic_fit:     g('i-why_now_strategic_fit') || null,
    success_metric:            g('i-success_metric') || null,
    technical_approach:        g('i-technical_approach') || null,
    integrations_data_sources: g('i-integrations_data_sources') || null,
    data_handled:              g('i-data_handled') || null,
    effort_estimate:           g('i-effort_estimate') || null,
    human_in_the_loop:         g('i-human_in_the_loop') || null,
    rollback_plan:             g('i-rollback_plan') || null,
    risk_flags:                parseCSV(g('i-risk_flags')),
    impact:                    num('i-impact'),
    ease:                      num('i-ease'),
    strategic_fit:             num('i-strategic_fit'),
    proposed_target_date:      g('i-proposed_target_date') || null,
    stakeholders:              g('i-stakeholders') || null,
    open_questions:            g('i-open_questions') || null,
    submitted_by:              profile.id,
    submitted_by_name:         profile.display_name,
  };
  const err = document.getElementById('intake-err');
  const res = await sb.from('ai_intake_submissions').insert(payload);
  if (res.error) { err.textContent = res.error.message; err.style.display = 'block'; return; }
  dismissModal(document.getElementById('intake-modal'));
  await fetchIntake(); renderIntake();
  showView('intake');
  showToast('Idea submitted for review');
}

function openIntakeDecision(id) {
  if (!isAdmin()) return;
  intakeDecisionId = id;
  const s = intake.find(x => x.id === id);
  const cur = s && s.leadership_decision && s.leadership_decision !== 'pending' ? s.leadership_decision : 'approved';
  document.getElementById('id-decision').value = cur;
  document.getElementById('id-notes').value = s?.decision_notes || '';
  document.getElementById('intake-decision-err').style.display = 'none';
  openModal(document.getElementById('intake-decision-modal'));
}

async function saveIntakeDecision(e) {
  e.preventDefault();
  const payload = {
    leadership_decision: document.getElementById('id-decision').value,
    decision_notes:      document.getElementById('id-notes').value.trim() || null,
    decided_by:          profile.id,
    decided_by_name:     profile.display_name,
    decided_at:          new Date().toISOString(),
  };
  const res = await sb.from('ai_intake_submissions').update(payload).eq('id', intakeDecisionId);
  const err = document.getElementById('intake-decision-err');
  if (res.error) { err.textContent = res.error.message; err.style.display = 'block'; return; }
  dismissModal(document.getElementById('intake-decision-modal'));
  intakeDecisionId = null;
  await fetchIntake(); renderIntake();
  showToast('Decision recorded');
}

// ---- Decisions ----
async function fetchDecisions() {
  const { data, error } = await sb.from('ai_decisions').select('*').order('created_at', { ascending: false });
  if (error) { console.error(error); showToast("Couldn't load decisions", 'err'); return; }
  decisions = data;
}

function renderDecisions() {
  const list = document.getElementById('decisions-list');
  const open = decisions.filter(d => !d.resolved_at).length;
  document.getElementById('decisions-count').textContent = `${decisions.length} total · ${open} open`;
  setBadge('decisions-badge', open);

  if (!decisions.length) {
    list.innerHTML = `<div class="card"><div class="card-row" style="cursor:default"><div class="card-main"><div class="card-meta">No decisions logged yet.</div></div></div></div>`;
    return;
  }
  const sorted = [...decisions].sort((a, b) => {
    const ar = a.resolved_at ? 1 : 0, br = b.resolved_at ? 1 : 0;
    if (ar !== br) return ar - br;   // open first
    return (URGENCY_RANK[a.urgency] ?? 9) - (URGENCY_RANK[b.urgency] ?? 9);
  });
  list.innerHTML = sorted.map(d => {
    const resolved = !!d.resolved_at;
    const meta = [
      d.related_project_text,
      d.who_decides ? 'decides: ' + d.who_decides : '',
      resolved ? 'resolved ' + formatWhen(d.resolved_at) : '',
    ].filter(Boolean).map(escapeHTML).join(' · ');
    return `
    <div class="card ${resolved ? 'resolved' : ''}" data-expandable="1">
      <div class="card-row" tabindex="0" role="button" aria-expanded="false">
        <div class="card-main">
          <div class="card-title">${escapeHTML(d.decision_needed)}</div>
          <div class="card-meta">${meta || '—'}</div>
        </div>
        <div class="card-side"><span class="pill pill-urgency-${escapeHTML((d.urgency || '').replace(/\s/g, ''))}">${escapeHTML(d.urgency || '')}</span></div>
      </div>
      <div class="card-detail">
        <div class="grid">
          ${field('Who decides', d.who_decides)}
          ${field('Related project', d.related_project_text)}
          ${field('Notes / context', d.notes_context)}
          ${resolved ? field('Resolution', (d.resolution_notes || '') + (d.resolved_by_name ? ` — ${d.resolved_by_name}` : '')) : ''}
        </div>
        ${isAdmin() ? `<div class="row-actions"><button data-decision-action="edit" data-id="${d.id}">${resolved ? 'Edit' : 'Manage / resolve'}</button></div>` : ''}
      </div>
    </div>`;
  }).join('');
  wireCards('decisions-list');
  list.querySelectorAll('[data-decision-action="edit"]').forEach(b =>
    b.addEventListener('click', e => { e.stopPropagation(); openDecisionModal(b.dataset.id); }));
}

function openDecisionModal(id) {
  if (!isAdmin()) return;
  showView('decisions');
  editingDecisionId = id;
  const d = id ? decisions.find(x => x.id === id) : null;
  document.getElementById('decision-title').textContent = id ? 'Edit decision' : 'Add decision';
  document.getElementById('d-urgency').value = d?.urgency || 'Soon';
  document.getElementById('d-who_decides').value = d?.who_decides || '';
  document.getElementById('d-decision_needed').value = d?.decision_needed || '';
  document.getElementById('d-related_project_text').value = d?.related_project_text || '';
  document.getElementById('d-notes_context').value = d?.notes_context || '';
  document.getElementById('d-resolution_notes').value = d?.resolution_notes || '';
  document.getElementById('d-resolution-wrap').style.display = id ? 'block' : 'none';
  document.getElementById('decision-delete').style.display = id ? 'inline-block' : 'none';
  document.getElementById('decision-resolve').style.display = (id && d && !d.resolved_at) ? 'inline-block' : 'none';
  document.getElementById('decision-err').style.display = 'none';
  openModal(document.getElementById('decision-modal'));
}

async function saveDecision(resolve) {
  const g = id => document.getElementById(id).value.trim();
  const err = document.getElementById('decision-err');
  if (!g('d-decision_needed')) { err.textContent = 'Decision needed is required.'; err.style.display = 'block'; return; }
  const payload = {
    urgency:              g('d-urgency'),
    decision_needed:      g('d-decision_needed'),
    who_decides:          g('d-who_decides') || null,
    related_project_text: g('d-related_project_text') || null,
    notes_context:        g('d-notes_context') || null,
    resolution_notes:     g('d-resolution_notes') || null,
  };
  if (resolve) {
    payload.resolved_at = new Date().toISOString();
    payload.resolved_by = profile.id;
    payload.resolved_by_name = profile.display_name;
  }
  let res;
  if (editingDecisionId) res = await sb.from('ai_decisions').update(payload).eq('id', editingDecisionId);
  else res = await sb.from('ai_decisions').insert(payload);
  if (res.error) { err.textContent = res.error.message; err.style.display = 'block'; return; }
  dismissModal(document.getElementById('decision-modal'));
  editingDecisionId = null;
  await fetchDecisions(); renderDecisions();
  showToast(resolve ? 'Marked resolved' : 'Decision saved');
}

async function deleteDecision() {
  if (!editingDecisionId) return;
  if (!confirm('Delete this decision? This cannot be undone.')) return;
  const { error } = await sb.from('ai_decisions').delete().eq('id', editingDecisionId);
  const err = document.getElementById('decision-err');
  if (error) { err.textContent = error.message; err.style.display = 'block'; return; }
  dismissModal(document.getElementById('decision-modal'));
  editingDecisionId = null;
  await fetchDecisions(); renderDecisions();
  showToast('Decision deleted');
}

// ============================================================================
// ACTIVITY DRAWER (audit log across all projects)
// ============================================================================
async function openActivity() {
  const d = document.getElementById('activity-drawer');
  d.hidden = false;
  document.body.style.overflow = 'hidden';
  const list = document.getElementById('activity-list');
  list.innerHTML = '<div class="act-empty">Loading…</div>';
  const { data, error } = await sb.from('ai_project_audit').select('*').order('changed_at', { ascending: false }).limit(60);
  if (error) { list.innerHTML = '<div class="act-empty">Couldn\'t load activity.</div>'; return; }
  if (!data.length) { list.innerHTML = '<div class="act-empty">No recent changes.</div>'; return; }
  const nameOf = id => { const p = projects.find(x => x.id === id); return p ? p.project_name : 'a project'; };
  list.innerHTML = data.map(r => `<div class="act-item">
    <div class="act-line"><strong>${escapeHTML(r.changed_by_name || 'Someone')}</strong> changed <strong>${escapeHTML(r.field_name)}</strong> on ${escapeHTML(nameOf(r.project_id))}</div>
    <div class="act-sub">${escapeHTML(String(r.old_value ?? '—'))} → ${escapeHTML(String(r.new_value ?? '—'))}</div>
    <div class="act-when">${formatWhen(r.changed_at)}</div>
  </div>`).join('');
}
function closeActivity() {
  document.getElementById('activity-drawer').hidden = true;
  if (!document.querySelector('.modal-backdrop.open')) document.body.style.overflow = '';
}

// ============================================================================
// ASK THE PORTFOLIO (AI) — calls the ask-portfolio edge function
// ============================================================================
function openAsk() {
  document.getElementById('ask-q').value = '';
  const a = document.getElementById('ask-answer');
  a.hidden = true; a.textContent = ''; a.className = 'ask-answer';
  openModal(document.getElementById('ask-modal'));
}
async function runAsk(e) {
  if (e) e.preventDefault();
  const q = document.getElementById('ask-q').value.trim();
  if (!q) return;
  const ans = document.getElementById('ask-answer');
  const go = document.getElementById('ask-go');
  ans.hidden = false; ans.className = 'ask-answer loading'; ans.textContent = 'Thinking…';
  go.disabled = true;
  try {
    const { data, error } = await sb.functions.invoke('ask-portfolio', { body: { question: q } });
    go.disabled = false;
    if (error || !data || data.error) {
      ans.className = 'ask-answer err';
      ans.textContent = (data && data.error) ? data.error
        : "The AI assistant isn't set up yet — deploy the ask-portfolio edge function and set ANTHROPIC_API_KEY.";
      return;
    }
    ans.className = 'ask-answer';
    ans.textContent = data.answer || 'No answer.';
  } catch (err) {
    go.disabled = false;
    ans.className = 'ask-answer err';
    ans.textContent = "Couldn't reach the AI assistant.";
  }
}

// ============================================================================
// COMMAND PALETTE (⌘K)
// ============================================================================
let cmdkItems = [], cmdkIndex = 0;

function cmdkActions() {
  const a = [
    { label: 'Go to Projects',  icon: 'table', run: () => showView('projects') },
    { label: 'Go to Intake',    icon: 'inbox', run: () => showView('intake') },
    { label: 'Go to Decisions', icon: 'flag',  run: () => showView('decisions') },
    { label: 'Go to Insights',  icon: 'chart', run: () => showView('insights') },
    { label: 'Toggle dark mode', icon: 'moon', run: () => toggleTheme() },
    { label: 'Export CSV',      icon: 'download', run: () => exportCSV() },
    { label: 'Submit a project idea', icon: 'plus', run: () => openIntakeModal() },
  ];
  if (isAdmin()) {
    a.unshift({ label: 'New project', icon: 'plus', run: () => openProjectModal(null) });
    a.unshift({ label: 'Ask the portfolio (AI)', icon: 'sparkle', run: () => openAsk() });
  }
  return a.map(x => ({ ...x, type: 'action', sub: 'Command' }));
}

// Subsequence fuzzy match; higher score = better, -1 = no match.
function fuzzy(q, text) {
  if (!q) return 0;
  q = q.toLowerCase(); text = text.toLowerCase();
  let ti = 0, score = 0;
  for (const ch of q) {
    const idx = text.indexOf(ch, ti);
    if (idx < 0) return -1;
    score += (idx === ti) ? 2 : 1;
    ti = idx + 1;
  }
  return score;
}

function openCmdk() {
  const bd = document.getElementById('cmdk');
  bd.hidden = false;
  document.body.style.overflow = 'hidden';
  const inp = document.getElementById('cmdk-input');
  inp.value = '';
  buildCmdk('');
  setTimeout(() => inp.focus(), 20);
}
function closeCmdk() {
  document.getElementById('cmdk').hidden = true;
  if (!document.querySelector('.modal-backdrop.open')) document.body.style.overflow = '';
}
function buildCmdk(q) {
  const items = [];
  projects.forEach(p => {
    const s = fuzzy(q, `${p.project_name} ${p.theme} ${(p.owners || []).join(' ')}`);
    if (q === '' || s >= 0) items.push({ type: 'project', label: p.project_name, sub: p.theme || 'Project', icon: 'table', score: s, id: p.id });
  });
  cmdkActions().forEach(a => { const s = fuzzy(q, a.label); if (q === '' || s >= 0) items.push({ ...a, score: s }); });
  if (q) items.sort((a, b) => b.score - a.score);
  cmdkItems = items.slice(0, 40);
  cmdkIndex = 0;
  renderCmdk();
}
function renderCmdk() {
  const list = document.getElementById('cmdk-list');
  if (!cmdkItems.length) { list.innerHTML = '<div class="cmdk-empty">No matches</div>'; return; }
  list.innerHTML = cmdkItems.map((it, i) =>
    `<div class="cmdk-item ${i === cmdkIndex ? 'sel' : ''}" data-i="${i}">${ic(it.icon || 'circle')}<span class="cmdk-label">${escapeHTML(it.label)}</span><span class="cmdk-sub">${escapeHTML(it.sub || '')}</span></div>`
  ).join('');
  list.querySelectorAll('.cmdk-item').forEach(el => {
    el.addEventListener('mousemove', () => { cmdkIndex = +el.dataset.i; updateCmdkSel(); });
    el.addEventListener('click', () => runCmdk(cmdkItems[+el.dataset.i]));
  });
}
function updateCmdkSel() {
  document.querySelectorAll('#cmdk-list .cmdk-item').forEach((el, i) => el.classList.toggle('sel', i === cmdkIndex));
  const sel = document.querySelector('#cmdk-list .cmdk-item.sel');
  if (sel) sel.scrollIntoView({ block: 'nearest' });
}
function runCmdk(it) {
  if (!it) return;
  closeCmdk();
  if (it.type === 'project') {
    showView('projects');
    deepOpenId = it.id; writeURL();
    setTimeout(() => {
      const row = document.querySelector(`.main-row[data-id="${it.id}"]`);
      const ex = document.querySelector(`.expandable-row[data-for="${it.id}"]`);
      if (row) {
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        if (ex && !ex.classList.contains('open')) { ex.classList.add('open'); row.setAttribute('aria-expanded', 'true'); }
      }
    }, 60);
  } else if (it.run) {
    it.run();
  }
}

// ============================================================================
// GO
// ============================================================================
init();
