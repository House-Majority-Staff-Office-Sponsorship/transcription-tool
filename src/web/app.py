import os
from pathlib import Path
from collections import deque

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func

from db.session import SessionLocal
from db.models import Video, Transcript

LOG_PATH = Path(os.getenv("LOG_PATH", "data/logs/transcription_tool.log"))

app = FastAPI(title="Transcription Tool Dashboard")


def _tail(path: Path, lines: int = 200) -> list[str]:
    """Read the last N lines from a file."""
    if not path.exists():
        return ["[No log file found yet]"]
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return list(deque(f, maxlen=lines))


@app.get("/_data/stats")
def stats():
    with SessionLocal() as session:
        total = session.scalar(select(func.count(Video.id))) or 0
        completed = session.scalar(
            select(func.count(Video.id)).where(Video.status == "completed")
        ) or 0
        pending = total - completed
    return {"total": total, "completed": completed, "pending": pending}


@app.get("/_data/videos")
def list_videos(limit: int = 50, offset: int = 0):
    with SessionLocal() as session:
        rows = session.scalars(
            select(Video).order_by(Video.created_at.desc()).offset(offset).limit(limit)
        ).all()
        return [
            {
                "id": v.id,
                "youtube_video_id": v.youtube_video_id,
                "title": v.title,
                "committee_code": v.committee_code,
                "status": v.status,
                "error_message": v.error_message,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "updated_at": v.updated_at.isoformat() if v.updated_at else None,
            }
            for v in rows
        ]


@app.get("/_data/videos/{video_id}")
def get_video(video_id: int):
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if not video:
            return {"error": "not found"}
        transcripts = []
        for t in video.transcripts:
            transcripts.append({
                "id": t.id,
                "model_size": t.model_size,
                "device": t.device,
                "compute_type": t.compute_type,
                "full_text": t.full_text[:2000] if t.full_text else "",
                "created_at": t.created_at.isoformat() if t.created_at else None,
            })
        return {
            "id": video.id,
            "youtube_video_id": video.youtube_video_id,
            "title": video.title,
            "committee_code": video.committee_code,
            "status": video.status,
            "error_message": video.error_message,
            "created_at": video.created_at.isoformat() if video.created_at else None,
            "transcripts": transcripts,
        }


@app.get("/_data/logs")
def get_logs(lines: int = 200):
    return {"lines": _tail(LOG_PATH, lines)}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return DASHBOARD_HTML


DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Transcription Tool</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; }
  .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
  h1 { font-size: 1.5rem; margin-bottom: 20px; color: #38bdf8; }
  .stats { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
  .stat-card { background: #1e293b; border-radius: 8px; padding: 16px 24px; flex: 1; min-width: 140px; }
  .stat-card .label { font-size: 0.75rem; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.05em; }
  .stat-card .value { font-size: 1.75rem; font-weight: 700; margin-top: 4px; }
  .stat-card .value.blue { color: #38bdf8; }
  .stat-card .value.green { color: #4ade80; }
  .stat-card .value.yellow { color: #facc15; }
  .tabs { display: flex; gap: 0; margin-bottom: 0; }
  .tab { padding: 10px 20px; background: #1e293b; border: none; color: #94a3b8; cursor: pointer; font-size: 0.875rem; border-radius: 8px 8px 0 0; }
  .tab.active { background: #1e293b; color: #38bdf8; border-bottom: 2px solid #38bdf8; }
  .panel { background: #1e293b; border-radius: 0 8px 8px 8px; padding: 20px; margin-bottom: 24px; min-height: 300px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #334155; font-size: 0.85rem; }
  th { color: #94a3b8; font-weight: 600; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.05em; }
  tr:hover { background: #334155; }
  .status { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
  .status.completed { background: #166534; color: #4ade80; }
  .status.pending, .status.processing { background: #854d0e; color: #facc15; }
  .status.error { background: #991b1b; color: #fca5a5; }
  .log-box { background: #0f172a; border-radius: 6px; padding: 16px; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.8rem; line-height: 1.6; max-height: 500px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; color: #cbd5e1; }
  .log-line-info { color: #38bdf8; }
  .log-line-error { color: #f87171; }
  .log-line-warn { color: #facc15; }
  .refresh-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
  .refresh-bar button { background: #334155; border: none; color: #e2e8f0; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 0.8rem; }
  .refresh-bar button:hover { background: #475569; }
  .refresh-bar .auto { font-size: 0.75rem; color: #64748b; }
  .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 100; justify-content: center; align-items: center; }
  .modal-overlay.show { display: flex; }
  .modal { background: #1e293b; border-radius: 8px; padding: 24px; max-width: 800px; width: 90%; max-height: 80vh; overflow-y: auto; }
  .modal h2 { font-size: 1.1rem; margin-bottom: 12px; color: #38bdf8; }
  .modal .close { float: right; background: none; border: none; color: #94a3b8; font-size: 1.2rem; cursor: pointer; }
  .modal pre { background: #0f172a; padding: 12px; border-radius: 6px; font-size: 0.8rem; white-space: pre-wrap; max-height: 400px; overflow-y: auto; }
  .yt-link { color: #38bdf8; text-decoration: none; }
  .yt-link:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="container">
  <h1>Transcription Tool Dashboard</h1>

  <div class="stats">
    <div class="stat-card"><div class="label">Total Videos</div><div class="value blue" id="stat-total">-</div></div>
    <div class="stat-card"><div class="label">Completed</div><div class="value green" id="stat-completed">-</div></div>
    <div class="stat-card"><div class="label">Pending</div><div class="value yellow" id="stat-pending">-</div></div>
  </div>

  <div class="tabs">
    <button class="tab active" onclick="showTab('videos')">Videos</button>
    <button class="tab" onclick="showTab('logs')">Logs</button>
  </div>

  <div class="panel" id="panel-videos">
    <div class="refresh-bar">
      <button onclick="loadVideos()">Refresh</button>
      <span class="auto">Auto-refreshes every 30s</span>
    </div>
    <table>
      <thead><tr><th>Title</th><th>Committee</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead>
      <tbody id="videos-tbody"></tbody>
    </table>
  </div>

  <div class="panel" id="panel-logs" style="display:none;">
    <div class="refresh-bar">
      <button onclick="loadLogs()">Refresh</button>
      <span class="auto">Auto-refreshes every 10s</span>
    </div>
    <div class="log-box" id="log-box"></div>
  </div>
</div>

<div class="modal-overlay" id="modal-overlay" onclick="closeModal(event)">
  <div class="modal">
    <button class="close" onclick="document.getElementById('modal-overlay').classList.remove('show')">&times;</button>
    <h2 id="modal-title"></h2>
    <div id="modal-body"></div>
  </div>
</div>

<script>
function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('panel-videos').style.display = name === 'videos' ? '' : 'none';
  document.getElementById('panel-logs').style.display = name === 'logs' ? '' : 'none';
  event.target.classList.add('active');
  if (name === 'logs') loadLogs();
  if (name === 'videos') loadVideos();
}

async function loadStats() {
  try {
    const r = await fetch('/_data/stats');
    const d = await r.json();
    document.getElementById('stat-total').textContent = d.total;
    document.getElementById('stat-completed').textContent = d.completed;
    document.getElementById('stat-pending').textContent = d.pending;
  } catch(e) { console.error(e); }
}

async function loadVideos() {
  try {
    const r = await fetch('/_data/videos?limit=50');
    const videos = await r.json();
    const tbody = document.getElementById('videos-tbody');
    if (!videos.length) { tbody.innerHTML = '<tr><td colspan="5" style="color:#64748b;text-align:center;padding:40px;">No videos processed yet</td></tr>'; return; }
    tbody.innerHTML = videos.map(v => `<tr>
      <td><a class="yt-link" href="https://youtube.com/watch?v=${v.youtube_video_id}" target="_blank">${esc(v.title)}</a></td>
      <td>${esc(v.committee_code)}</td>
      <td><span class="status ${v.status}">${v.status}</span></td>
      <td>${v.created_at ? new Date(v.created_at).toLocaleString() : '-'}</td>
      <td><button onclick="viewVideo(${v.id})" style="background:#334155;border:none;color:#38bdf8;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:0.75rem;">View</button></td>
    </tr>`).join('');
  } catch(e) { console.error(e); }
}

async function viewVideo(id) {
  const r = await fetch(`/_data/videos/${id}`);
  const v = await r.json();
  document.getElementById('modal-title').textContent = v.title;
  let html = `<p style="margin-bottom:8px;color:#94a3b8;font-size:0.85rem;">YouTube ID: <a class="yt-link" href="https://youtube.com/watch?v=${v.youtube_video_id}" target="_blank">${v.youtube_video_id}</a> | Committee: ${esc(v.committee_code)} | Status: ${v.status}</p>`;
  if (v.transcripts && v.transcripts.length) {
    const t = v.transcripts[0];
    html += `<p style="margin-bottom:8px;color:#94a3b8;font-size:0.8rem;">Model: ${t.model_size} | Device: ${t.device} | Compute: ${t.compute_type}</p>`;
    html += `<pre>${esc(t.full_text)}</pre>`;
  } else {
    html += '<p style="color:#64748b;">No transcript data yet.</p>';
  }
  document.getElementById('modal-body').innerHTML = html;
  document.getElementById('modal-overlay').classList.add('show');
}

function closeModal(e) { if (e.target === e.currentTarget) e.currentTarget.classList.remove('show'); }

async function loadLogs() {
  try {
    const r = await fetch('/_data/logs?lines=300');
    const d = await r.json();
    const box = document.getElementById('log-box');
    box.innerHTML = d.lines.map(l => {
      let cls = '';
      if (l.includes('ERROR')) cls = 'log-line-error';
      else if (l.includes('WARNING')) cls = 'log-line-warn';
      else if (l.includes('INFO')) cls = 'log-line-info';
      return `<span class="${cls}">${esc(l)}</span>`;
    }).join('');
    box.scrollTop = box.scrollHeight;
  } catch(e) { console.error(e); }
}

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

loadStats();
loadVideos();
setInterval(loadStats, 30000);
setInterval(loadVideos, 30000);
setInterval(() => { if (document.getElementById('panel-logs').style.display !== 'none') loadLogs(); }, 10000);
</script>
</body>
</html>
"""
