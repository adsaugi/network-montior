// ═══════════════════════════════════════════════════════════════════
//  REAL-TIME HOMELAB TOPOLOGY (Tech Theme)
// ═══════════════════════════════════════════════════════════════════

const canvas  = document.getElementById('canvas');
const ctx     = canvas.getContext('2d');
const tip     = document.getElementById('tip');
const tipChart = document.getElementById('tip-chart');
const tcx     = tipChart.getContext('2d');

let width = 0, height = 0;
let scale = 1, panX = 0, panY = 0;
let targetPanX = null, targetPanY = null;

const toastContainer = document.getElementById('toast-container');
let prevOnlineState = {};

let themeColors = { bg: '#000000', text: '#e2e8f0', sub: '#64748b', off: '#475569', drag: '#1f242e', sel: '#2dd4bf', act: '#3b82f6', aur: 'rgba(255,255,255,0.02)', grid: '#1f242e' };
function toggleTheme() {
  const isLight = document.body.classList.toggle('light-mode');
  const btn = document.getElementById('theme-btn');
  btn.textContent = isLight ? '🌙 DARK MODE' : '☀️ LIGHT MODE';
  if (isLight) {
    themeColors = { bg: '#ffffff', text: '#0f172a', sub: '#475569', off: '#94a3b8', drag: '#e2e8f0', sel: '#2dd4bf', act: '#3b82f6', aur: 'rgba(0,0,0,0.05)', grid: '#cbd5e1' };
  } else {
    themeColors = { bg: '#000000', text: '#e2e8f0', sub: '#64748b', off: '#475569', drag: '#1f242e', sel: '#2dd4bf', act: '#3b82f6', aur: 'rgba(255,255,255,0.02)', grid: '#1f242e' };
  }
}

function isNodeVisible(n) {
  let curr = nodes.find(x => x.id === n.parent);
  while(curr) {
    if (curr.collapsed) return false;
    curr = nodes.find(x => x.id === curr.parent);
  }
  return true;
}

// ── Default scaffold ────────────────────────────────────────────
const DEFAULTS = [
  { id:'router',   label:'ISP GATEWAY',   sub:'192.168.1.1',  kind:'router',  parent:null,      online:true },
  { id:'proxmox',  label:'PROXMOX CORE',  sub:'192.168.1.99', kind:'proxmox', parent:'router',  online:true },
  { id:'vm-100',   label:'UBUNTU VM',     sub:'VM 100',       kind:'vm',      parent:'proxmox', online:true },
  { id:'vm-101',   label:'WINDOWS 11',    sub:'VM 101',       kind:'vm',      parent:'proxmox', online:true },
  { id:'lxc-102',  label:'DOCKER LXC',    sub:'LXC 102',      kind:'lxc',     parent:'proxmox', online:true },
  { id:'iphone1',  label:'IPHONE',        sub:'192.168.1.14', kind:'apple',   parent:'router',  online:true },
  { id:'pc1',      label:'LAPTOP',        sub:'192.168.1.20', kind:'device',  parent:'router',  online:true },
];

let nodes    = [];
let packets  = [];
let bwHistory = {};
const MAX_HIST = 20;

let _lastNodeIds = '';
let searchQuery = '';

function savedPos(id) {
  try {
    const s = localStorage.getItem('pos_' + id);
    return s ? JSON.parse(s) : null;
  } catch(e) { return null; }
}
function savePos(id, x, y) {
  localStorage.setItem('pos_' + id, JSON.stringify({x,y}));
}
function savePosAll() {
  nodes.forEach(n => { if (n.x) savePos(n.id, n.x, n.y); });
}
function resetLayout() {
  localStorage.clear();
  nodes.forEach(n => { n.x = undefined; n.y = undefined; });
  layout(); rebuildPackets();
}
function toggleGrid() {
  document.body.classList.toggle('no-grid');
}

function layout() {
  const W = window.innerWidth, H = window.innerHeight - 90;
  const existPos = {};
  nodes.forEach(n => { if (n.x !== undefined) existPos[n.id] = {x:n.x, y:n.y}; });

  nodes.forEach(n => {
    if (existPos[n.id]) { n.x = existPos[n.id].x; n.y = existPos[n.id].y; return; }
    const sp = savedPos(n.id);
    if (sp) { n.x = sp.x; n.y = sp.y; return; }

    if (!isNodeVisible(n)) return;

    const cy = H / 2;
    if (n.id === 'router') {
      n.x = Math.max(100, W * 0.15); n.y = cy;
    } else if (n.id === 'proxmox') {
      n.x = Math.max(300, W * 0.42); n.y = Math.max(100, cy - 160);
    } else if (n.id === 'lxc-103' || (typeof adguardId !== 'undefined' && n.id === adguardId)) {
      n.x = Math.max(300, W * 0.42); n.y = cy + 120;
    } else if (n.id === 'tailscale') {
      n.x = Math.max(300, W * 0.42); n.y = cy + 280;
    } else if (n.parent === 'proxmox') {
      const sibs = nodes.filter(x => x.parent === 'proxmox');
      const i = sibs.indexOf(n);
      const startY = Math.max(80, cy - 160) - ((sibs.length - 1) * 75) / 2;
      n.x = Math.max(500, W * 0.75); n.y = startY + (i * 75);
    } else if (n.parent === 'tailscale') {
      const sibs = nodes.filter(x => x.parent === 'tailscale');
      const i = sibs.indexOf(n);
      const startY = (cy + 280) - ((sibs.length - 1) * 75) / 2;
      n.x = Math.max(500, W * 0.75); n.y = startY + (i * 75);
    } else if (n.parent === 'lxc-103' || (typeof adguardId !== 'undefined' && adguardId && n.parent === adguardId)) {
      const pId = (typeof adguardId !== 'undefined' && adguardId) ? adguardId : 'lxc-103';
      const sibs = nodes.filter(x => x.parent === pId);
      const i = sibs.indexOf(n);
      const startY = (cy + 120) - ((sibs.length - 1) * 75) / 2;
      n.x = Math.max(500, W * 0.75); n.y = startY + (i * 75);
    } else if (n.parent === 'router') {
      const sibs = nodes.filter(x => x.parent === 'router' && x.id !== 'proxmox' && x.id !== 'tailscale' && x.id !== 'lxc-103');
      const i = sibs.indexOf(n);
      const startY = cy + 100;
      n.x = Math.max(250, W * 0.35); n.y = startY + (i * 75);
    } else {
      const pNode = nodes.find(x => x.id === n.parent);
      if (pNode && pNode.x !== undefined) {
        const sibs = nodes.filter(x => x.parent === n.parent);
        const i = sibs.indexOf(n);
        const startY = pNode.y - ((sibs.length - 1) * 75) / 2;
        n.x = pNode.x + 250;
        n.y = startY + (i * 75);
      }
    }
  });
}

const NORMAL_SPEED = 0.003;

function bwToSpeed(kbps) {
  return NORMAL_SPEED;
}

function rebuildPackets() {
  packets = [];
  nodes.forEach((n, i) => {
    if (!n.parent || !n.online) return;
    const pi = nodes.findIndex(p => p.id === n.parent);
    if (pi < 0) return;
    packets.push({ fi:pi, ti:i, t:Math.random(), dir:'dl', nodeIdx:i });
    packets.push({ fi:i,  ti:pi, t:Math.random(), dir:'ul', nodeIdx:i });
  });
}

function applyLiveData(data) {
  const pveIPSet = new Set(data.pveIPs || []);
  const desired = [];

  let adguardId = null;
  (data.vms||[]).forEach(v => {
    if (v.vmid === 103 || (v.name && v.name.toLowerCase().includes('adguard'))) {
      adguardId = v.id;
    }
  });

  let pveRx = 0, pveTx = 0;
  (data.vms||[]).forEach(v => { pveRx += v.rxKbps||0; pveTx += v.txKbps||0; });

  desired.push({ id:'router', label:'ISP GATEWAY', sub:'192.168.1.1', kind:'router', parent:null, online:true, tRx:data.hostRx||0, tTx:data.hostTx||0, w:180, h:50 });
  desired.push({ id:'proxmox', label:'PROXMOX CORE', sub:'192.168.1.99', kind:'proxmox', parent:'router', online:!data.pveError, tRx:pveRx, tTx:pveTx, w:180, h:50 });

  const usedTailscaleIds = new Set();

  (data.vms||[]).forEach(v => {
    let finalIp = v.ip;
    if (!finalIp && v.online) {
      finalIp = `192.168.1.${v.vmid}`;
      pveIPSet.add(finalIp);
    }

    let subText = `${finalIp||'NO IP'} | VM ${v.vmid}`;
    let totalRx = v.rxKbps || 0;
    let totalTx = v.txKbps || 0;

    if (data.tailscale) {
      const tsMatch = data.tailscale.find(t => t.name.toLowerCase() === (v.name||'').toLowerCase());
      if (tsMatch) {
        subText = `${finalIp||'NO IP'} / ${tsMatch.ip}`;
        totalRx += tsMatch.rxKbps || 0;
        totalTx += tsMatch.txKbps || 0;
        usedTailscaleIds.add(tsMatch.id);
      }
    }

    // AdGuard Gateway connects directly to ISP GATEWAY as the network gateway
    let vmParent = (v.id === adguardId) ? 'router' : 'proxmox';
    desired.push({ id:v.id, label:(v.name||v.id).toUpperCase(), sub:subText, kind:v.type.toLowerCase().includes('lxc')?'lxc':'vm', parent:vmParent, online:v.online, tRx:totalRx, tTx:totalTx, ip:finalIp, cpu:v.cpu, memMB:v.memMB, w:190, h:50 });
  });

  if (data.tailscale && data.tailscale.length > 0) {
    const remainingTs = data.tailscale.filter(t => !usedTailscaleIds.has(t.id));
    if (remainingTs.length > 0) {
      let vpnParentId = 'router';
      const vpnVm = (data.vms||[]).find(v => (v.name||'').toLowerCase() === 'vpn' || v.vmid === 104);
      if (vpnVm) {
        vpnParentId = vpnVm.id;
      } else {
        let tsRx = 0, tsTx = 0;
        data.tailscale.forEach(t => { tsRx += t.rxKbps||0; tsTx += t.txKbps||0; });
        desired.push({ id:'tailscale', label:'TAILSCALE VPN', sub:'100.x.x.x', kind:'proxmox', parent:'router', online:true, tRx:tsRx, tTx:tsTx, w:180, h:50 });
        vpnParentId = 'tailscale';
      }

      remainingTs.forEach(t => {
        let subText = t.ip || 'NO IP';
        if (t.isSelf) subText += ' (THIS DEVICE)';
        desired.push({
          id: t.id,
          label: (t.name || 'UNKNOWN').toUpperCase(),
          sub: subText,
          kind: 'vm',
          parent: vpnParentId,
          online: t.online,
          tRx: t.rxKbps,
          tTx: t.txKbps,
          ip: t.ip,
          w: 180, h: 50
        });
      });
    }
  }

  // Deduplicate and filter arpDevices
  const GENERIC_NAMES = new Set(['WIFICLIENT', 'CLIENT', 'DEVICE', 'ANDROID', 'APPLE', 'IPHONEIPAD', 'UNKNOWN', '']);
  const activeArp = (data.arpDevices || []).filter(d => {
    let label = (d.name || d.id || '').toUpperCase();
    if (label.includes('(')) label = label.split('(')[0].trim();
    const isMobileClient = (d.type === 'apple' || d.type === 'android' || label.includes('IPAD') || label.includes('PHONE') || label.includes('GALAXY'));
    if (pveIPSet.has(d.ip) && !isMobileClient) return false;
    return true;
  });

  function getDevScore(d) {
    let s = 0;
    if ((d.rxKbps || 0) > 0 || (d.txKbps || 0) > 0) s += 1000;
    s += Math.min(500, ((d.rxBytes || 0) + (d.txBytes || 0)) / (1024 * 1024));
    s += (d.dnsQueries || 0) * 2;
    if (d.mac && d.mac !== '00:00:00:00:00:00') s += 50;
    return s;
  }

  function getDevNorm(d) {
    let raw = (d.name || d.id || '').toUpperCase();
    if (raw.includes('(')) raw = raw.split('(')[0].trim();
    let norm = raw.replace(/[^A-Z0-9]/g, '');
    if (GENERIC_NAMES.has(norm) || /^\d+$/.test(norm) || norm.length < 3) return null;
    return norm;
  }

  const dropDevIps = new Set();
  const macGroups = {};
  activeArp.forEach(d => {
    if (d.mac && d.mac !== '00:00:00:00:00:00') {
      if (!macGroups[d.mac]) macGroups[d.mac] = [];
      macGroups[d.mac].push(d);
    }
  });
  Object.values(macGroups).forEach(group => {
    if (group.length > 1) {
      group.sort((a, b) => getDevScore(b) - getDevScore(a));
      group.slice(1).forEach(loser => dropDevIps.add(loser.ip));
    }
  });

  const nameGroups = {};
  activeArp.forEach(d => {
    if (dropDevIps.has(d.ip)) return;
    const norm = getDevNorm(d);
    if (norm) {
      if (!nameGroups[norm]) nameGroups[norm] = [];
      nameGroups[norm].push(d);
    }
  });
  Object.values(nameGroups).forEach(group => {
    if (group.length > 1) {
      group.sort((a, b) => getDevScore(b) - getDevScore(a));
      group.slice(1).forEach(loser => dropDevIps.add(loser.ip));
    }
  });

  activeArp.filter(d => !dropDevIps.has(d.ip)).forEach(d => {
    let label = (d.name || d.id).toUpperCase();
    if (label.includes('(')) label = label.split('(')[0].trim();
    if (label.includes('IPHONE') || label.includes('IPAD') || label.includes('APPLE')) d.type = 'apple';
    if (label.includes('ANDROID') || label.includes('GALAXY') || label.includes('SAMSUNG')) d.type = 'android';

    let subText = d.ip;
    if (d.dnsQueries) subText += ` | ${d.dnsQueries} DNS`;
    let wifiParent = adguardId || 'router';
    desired.push({ id:d.id, label:label, sub:subText, kind:d.type||'device', parent:wifiParent, online:d.online, tRx:d.rxKbps||0, tTx:d.txKbps||0, ip:d.ip, dnsQueries:d.dnsQueries||0, rxBytes:d.rxBytes||0, txBytes:d.txBytes||0, w:180, h:50 });
  });

  desired.forEach(n => {
    if (prevOnlineState[n.id] !== undefined) {
      if (prevOnlineState[n.id] && !n.online) showToast(`⚠ ${n.label} went OFFLINE`, 'red');
      else if (!prevOnlineState[n.id] && n.online) showToast(`✓ ${n.label} is ONLINE`, 'green');
    }
    prevOnlineState[n.id] = n.online;
  });

  const curIds = desired.map(d=>d.id).sort().join(',');
  if (curIds !== _lastNodeIds) {
    _lastNodeIds = curIds;
    const old = {}; nodes.forEach(n => { old[n.id] = n; });
    nodes = desired.map(d => {
      const o = old[d.id];
      if (o) return { ...o, ...d };
      return { ...d, rx:0, tx:0 };
    });
    layout();
    rebuildPackets();
  } else {
    const desiredMap = {};
    desired.forEach(d => { desiredMap[d.id] = d; });
    nodes.forEach(n => {
      const d = desiredMap[n.id];
      if (!d) return;
      n.tRx = d.tRx; n.tTx = d.tTx; n.online = d.online; n.label = d.label; n.sub = d.sub; n.ip = d.ip; n.cpu = d.cpu; n.memMB = d.memMB; n.dnsQueries = d.dnsQueries; n.rxBytes = d.rxBytes; n.txBytes = d.txBytes;
    });
  }

  nodes.forEach(n => {
    if (!bwHistory[n.id]) bwHistory[n.id] = [];
    bwHistory[n.id].push({ rx: n.tRx, tx: n.tTx });
    if (bwHistory[n.id].length > MAX_HIST) bwHistory[n.id].shift();
  });

  updateStats(data);
}

function fmtSpeed(kbps) {
  if (!kbps || kbps === 0) return '0 Mbps';
  const mbps = (kbps * 1024 * 8) / 1000000;
  return mbps < 1 ? mbps.toFixed(2) + ' Mbps' : mbps.toFixed(1) + ' Mbps';
}
function fmtBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}
function updateStats(data) {
  const vms = nodes.filter(n => n.parent === 'proxmox');
  const clients = nodes.filter(n => n.parent === 'router' && n.id !== 'proxmox');
  document.getElementById('st-vms').textContent = `${vms.filter(n=>n.online).length} / ${vms.length}`;
  document.getElementById('st-clients').textContent = clients.length;
  document.getElementById('st-dl').textContent = fmtSpeed(data.hostRx || 0);
  document.getElementById('st-ul').textContent = fmtSpeed(data.hostTx || 0);

  const rx = data.hostRxBytes != null ? data.hostRxBytes : (data.trafficStats && data.trafficStats.all ? data.trafficStats.all.rx : 0);
  const tx = data.hostTxBytes != null ? data.hostTxBytes : (data.trafficStats && data.trafficStats.all ? data.trafficStats.all.tx : 0);
  document.getElementById('st-total').textContent = `${fmtBytes(rx)} / ${fmtBytes(tx)}`;

  document.getElementById('st-lag').textContent = data.ts ? ((Date.now()/1000 - data.ts)).toFixed(1) + 's' : '—';
}

let evtSource = null;
function connectSSE() {
  if (evtSource) { evtSource.close(); evtSource = null; }
  setPillState('warn', 'CONNECTING...');
  evtSource = new EventSource('/api/stream');
  evtSource.onopen = () => setPillState('live', 'CONNECTED');
  evtSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      applyLiveData(data);
      setPillState('live', data.pveError ? `PVE ERROR` : 'SYNCED');
    } catch(err) {}
  };
  evtSource.onerror = () => {
    setPillState('error', 'OFFLINE');
    evtSource.close(); evtSource = null;
    setTimeout(connectSSE, 4000);
  };
}
function reconnectSSE() {
  if (evtSource) { evtSource.close(); evtSource = null; }
  connectSSE();
}

function showToast(msg, type) {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  toastContainer.appendChild(el);
  setTimeout(() => el.classList.add('show'), 10);
  setTimeout(() => {
    el.classList.add('fade');
    setTimeout(() => el.remove(), 300);
  }, 4000);
  while (toastContainer.children.length > 5) {
    toastContainer.firstElementChild.remove();
  }
}

function setPillState(state, text) {
  const pill = document.getElementById('sse-pill');
  const dot  = document.getElementById('pill-dot');
  const txt  = document.getElementById('pill-txt');
  pill.className = state === 'live' ? 'live' : state;
  dot.className  = state === 'live' ? 'pill-dot live' : 'pill-dot';
  txt.textContent = text;
}

let frameCount = 0, fpsT0 = 0, rafId = null;
let prevTs = 0;
const LERP_SPEED = 0.12;
const ripples = [];

function render(ts) {
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, width, height);

  ctx.setTransform(scale, 0, 0, scale, panX, panY);

  const dt = Math.min(ts - (prevTs || ts), 50);
  prevTs = ts;
  const dtNorm = dt / 16.667;

  if (targetPanX !== null && targetPanY !== null) {
    const panLerp = 1 - Math.pow(1 - 0.1, dtNorm);
    panX += (targetPanX - panX) * panLerp;
    panY += (targetPanY - panY) * panLerp;
    if (Math.abs(targetPanX - panX) < 0.5 && Math.abs(targetPanY - panY) < 0.5) {
      panX = targetPanX;
      panY = targetPanY;
      targetPanX = null;
      targetPanY = null;
    }
  }

  frameCount++;
  if (ts - fpsT0 >= 1000) {
    document.getElementById('fps-badge').textContent = `${Math.round(frameCount * 1000 / (ts - fpsT0))} FPS`;
    frameCount = 0; fpsT0 = ts;
  }

  const lerpAlpha = 1 - Math.pow(1 - LERP_SPEED, dtNorm);
  nodes.forEach(n => {
    if (n.tRx !== undefined) n.rx = n.rx + (n.tRx - n.rx) * lerpAlpha;
    if (n.tTx !== undefined) n.tx = n.tx + (n.tTx - n.tx) * lerpAlpha;
    if (n.rx < 0.5) n.rx = 0;
    if (n.tx < 0.5) n.tx = 0;
  });

  function getBezierPts(x1, y1, x2, y2) {
    const dx = Math.abs(x2 - x1);
    const offset = Math.max(dx * 0.5, 30);
    return [
      { x: x1, y: y1 },
      { x: x1 + offset, y: y1 },
      { x: x2 - offset, y: y2 },
      { x: x2, y: y2 }
    ];
  }

  function pointOnBezier(pts, t) {
    const mt = 1 - t;
    const mt2 = mt * mt;
    const t2 = t * t;

    const a = mt2 * mt;
    const b = mt2 * t * 3;
    const c = mt * t2 * 3;
    const d = t * t2;

    return {
      x: a * pts[0].x + b * pts[1].x + c * pts[2].x + d * pts[3].x,
      y: a * pts[0].y + b * pts[1].y + c * pts[2].y + d * pts[3].y
    };
  }

  const visibleNodes = nodes.filter(isNodeVisible);

  visibleNodes.forEach(n => {
    if (!n.parent || n.x === undefined) return;
    const p = nodes.find(x => x.id === n.parent);
    if (!p || p.x === undefined || !isNodeVisible(p)) return;

    const pts = getBezierPts(p.x + p.w/2, p.y, n.x - n.w/2, n.y);

    ctx.save();
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    ctx.bezierCurveTo(pts[1].x, pts[1].y, pts[2].x, pts[2].y, pts[3].x, pts[3].y);

    const bw = (n.rx||0) + (n.tx||0);
    const isActive = bw > 0;

    const palette = ['#f47a60', '#fcdb6d', '#78c0f5', '#6dcd9e', '#c47eee', '#082a5c', '#f472b6', '#2dd4bf'];
    let hash = 0;
    for(let i=0; i<n.id.length; i++) hash += n.id.charCodeAt(i);
    const flowColor = palette[hash % palette.length];

    let opacity = 0.25;
    if (bw > 0) {
      opacity = Math.min(0.55, 0.25 + (bw / 3000));
      ctx.shadowColor = flowColor;
      ctx.shadowBlur = Math.min(25, 10 + bw / 500);
    }

    ctx.globalAlpha = opacity;
    ctx.strokeStyle = flowColor;
    ctx.lineWidth = isActive ? Math.max(1.5, Math.min(20, 1.5 + bw/300)) : 1.5;
    ctx.stroke();
    ctx.restore();
  });

  packets.forEach(pk => {
    if (pk.fi >= nodes.length || pk.ti >= nodes.length) return;
    const fn = nodes[pk.fi], tn = nodes[pk.ti];
    if (!fn || !tn || fn.x === undefined || tn.x === undefined || !isNodeVisible(fn) || !isNodeVisible(tn)) return;

    const leafNode = nodes[pk.nodeIdx] || tn;
    const bw = (leafNode.rx || 0) + (leafNode.tx || 0);

    const parentNode = (fn.id === leafNode.id) ? nodes[pk.ti] : nodes[pk.fi];
    const childNode = (fn.id === leafNode.id) ? fn : tn;
    const dist = Math.abs((parentNode.x + parentNode.w/2) - (childNode.x - childNode.w/2)) + Math.abs(parentNode.y - childNode.y);

    const streamBw = (pk.dir === 'ul') ? (leafNode.tx||0) : (leafNode.rx||0);
    const dotRadius = Math.max(2.5, Math.min(10, 2.5 + streamBw / 400));

    let pts;
    const isUl = (fn.id === leafNode.id);
    let dotColor = '#f472b6';
    if (isUl) {
      const p = nodes[pk.ti];
      pts = getBezierPts(p.x + p.w/2, p.y, fn.x - fn.w/2, fn.y);
      dotColor = '#f472b6';
    } else {
      const p = nodes[pk.fi];
      pts = getBezierPts(p.x + p.w/2, p.y, tn.x - tn.w/2, tn.y);
      dotColor = '#34d399';
    }

    const speed = (2.5 * dtNorm) / Math.max(dist, 50);
    pk.t += speed;
    if (pk.t >= 1) {
      pk.t -= 1;
      const impactPt = isUl ? pts[0] : pts[3];
      const targetId = isUl ? nodes[pk.ti].id : tn.id;
      const targetNode = nodes.find(x => x.id === targetId);
      const boxLimit = targetNode ? Math.min(targetNode.w, targetNode.h) / 2 - 2 : 20;
      ripples.push({ nodeId: targetId, x: impactPt.x, y: impactPt.y, r: dotRadius, maxR: Math.min(boxLimit, dotRadius + Math.min(20, 5 + bw/200)), color: dotColor, alpha: 0.9 });
    }

    ctx.save();
    ctx.shadowColor = dotColor;
    ctx.shadowBlur = Math.max(10, dotRadius * 2);
    ctx.fillStyle = dotColor;

    let t = isUl ? (1 - pk.t) : pk.t;
    t = t % 1.0;
    if (t < 0) t += 1.0;

    const pos = pointOnBezier(pts, t);
    ctx.beginPath();
    ctx.arc(pos.x, pos.y, dotRadius, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  });

  for (let i = ripples.length - 1; i >= 0; i--) {
    const r = ripples[i];
    r.r += 0.8 * dtNorm;
    r.alpha -= 0.02 * dtNorm;
    if (r.alpha <= 0 || r.r >= r.maxR) ripples.splice(i, 1);
  }

  visibleNodes.forEach((n, i) => {
    if (n.x === undefined) return;
    const isHov = nodes.indexOf(n) === hovered;
    const isDrag = nodes.indexOf(n) === dragging;
    const nx = n.x - n.w/2, ny = n.y - n.h/2;
    const isActive = (n.rx > 1 || n.tx > 1) && n.online;
    const isSel = selected.has(nodes.indexOf(n));
    const borderColor = isDrag ? themeColors.text : isSel ? themeColors.sel : (isHov || isActive ? themeColors.act : themeColors.grid);
    const lineW = (isDrag || isHov || isSel) ? 1.5 : 1;

    const matchesSearch = !searchQuery ||
      n.label.toLowerCase().includes(searchQuery) ||
      n.sub.toLowerCase().includes(searchQuery) ||
      (n.ip && n.ip.toLowerCase().includes(searchQuery));

    if (!matchesSearch && searchQuery) {
      ctx.globalAlpha = 0.15;
    } else {
      ctx.globalAlpha = 1;
    }

    if (isActive) {
      const auraIntensity = Math.min(40, 10 + (n.rx + n.tx) / 300);
      ctx.shadowColor = borderColor;
      ctx.shadowBlur = auraIntensity;
    } else {
      ctx.shadowBlur = 0;
    }
    ctx.fillStyle = isDrag ? themeColors.drag : themeColors.bg;
    ctx.fillRect(nx, ny, n.w, n.h);
    ctx.shadowBlur = 0;

    ctx.save();
    ctx.beginPath();
    ctx.rect(nx, ny, n.w, n.h);
    ctx.clip();
    ripples.forEach(r => {
      if (r.nodeId !== n.id) return;
      ctx.globalAlpha = r.alpha;
      ctx.strokeStyle = r.color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(r.x, r.y, r.r, 0, Math.PI * 2);
      ctx.stroke();
    });
    ctx.restore();
    ctx.globalAlpha = 1;
    ctx.strokeStyle = borderColor;
    ctx.lineWidth = lineW;
    ctx.strokeRect(nx, ny, n.w, n.h);

    if (isSel) {
      ctx.save();
      ctx.globalAlpha = 0.15;
      ctx.fillStyle = themeColors.sel;
      ctx.fillRect(nx, ny, n.w, n.h);
      ctx.restore();
    }

    if (isActive) {
      ctx.fillStyle = themeColors.act;
      ctx.fillRect(nx + n.w - 12, ny + n.h/2 - 2, 4, 4);
    }

    if (!n.online) {
      ctx.fillStyle = themeColors.aur;
      ctx.fillRect(nx, ny, n.w, n.h);
    }

    ctx.font = '600 12px "JetBrains Mono", monospace';
    ctx.fillStyle = n.online ? themeColors.text : themeColors.off;
    ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    ctx.fillText(truncate(n.label, 18), nx + 15, ny + 18);

    ctx.font = '400 10px "JetBrains Mono", monospace';
    ctx.fillStyle = themeColors.sub;
    ctx.fillText(truncate(n.sub, 22), nx + 15, ny + 35);

    if (n.collapsed) {
      const childrenCount = nodes.filter(x => x.parent === n.id).length;
      if (childrenCount > 0) {
        ctx.fillStyle = themeColors.drag;
        ctx.beginPath();
        ctx.roundRect(nx + n.w/2 - 25, ny + n.h - 8, 50, 16, 8);
        ctx.fill();
        ctx.fillStyle = themeColors.text;
        ctx.font = '600 9px "JetBrains Mono", monospace';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(`+${childrenCount} VMs`, nx + n.w/2, ny + n.h);
      }
    }
  });

  if (lasso) {
    const lx = Math.min(lasso.x0, lasso.x1);
    const ly = Math.min(lasso.y0, lasso.y1);
    const lw = Math.abs(lasso.x1 - lasso.x0);
    const lh = Math.abs(lasso.y1 - lasso.y0);
    ctx.save();
    ctx.globalAlpha = 0.15;
    ctx.fillStyle = '#2dd4bf';
    ctx.fillRect(lx, ly, lw, lh);
    ctx.restore();
    ctx.save();
    ctx.globalAlpha = 0.8;
    ctx.strokeStyle = '#2dd4bf';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 3]);
    ctx.strokeRect(lx, ly, lw, lh);
    ctx.restore();
  }

  rafId = requestAnimationFrame(render);
}

function truncate(str, max) {
  if (!str) return '';
  return str.length > max ? str.slice(0, max-1) + '…' : str;
}

function drawSparkline(id) {
  const hist = bwHistory[id] || [];
  const cw = 190, ch = 36;
  tcx.clearRect(0, 0, cw, ch);
  if (hist.length < 2) return;

  const maxVal = Math.max(...hist.map(h => Math.max(h.rx, h.tx)), 1);

  tcx.beginPath();
  hist.forEach((h, i) => {
    const x = (i / (MAX_HIST-1)) * cw;
    const y = ch - (h.rx / maxVal) * (ch - 2) - 1;
    i === 0 ? tcx.moveTo(x, y) : tcx.lineTo(x, y);
  });
  tcx.strokeStyle = '#34d399'; tcx.lineWidth = 1.5; tcx.stroke();

  tcx.beginPath();
  hist.forEach((h, i) => {
    const x = (i / (MAX_HIST-1)) * cw;
    const y = ch - (h.tx / maxVal) * (ch - 2) - 1;
    i === 0 ? tcx.moveTo(x, y) : tcx.lineTo(x, y);
  });
  tcx.strokeStyle = '#f472b6'; tcx.lineWidth = 1.5; tcx.stroke();
}

function resize() {
  width = canvas.width = window.innerWidth;
  height = canvas.height = window.innerHeight;
  layout();
  rebuildPackets();
}
window.addEventListener('resize', resize);

let hovered = -1, dragging = -1, dragOffX = 0, dragOffY = 0;
let selected = new Set();
let lasso = null;

let activePointers = new Map();
let isPanning = false, lastPanX = 0, lastPanY = 0;
let initialPinchDist = null, initialPinchScale = 1;
let lastClick = 0, lastClickNode = null;

function screenToWorld(x, y) {
  return { x: (x - panX) / scale, y: (y - panY) / scale };
}

canvas.addEventListener('wheel', e => {
  e.preventDefault();
  targetPanX = null;
  targetPanY = null;
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  if (e.ctrlKey) {
    const zoomFactor = Math.exp(-e.deltaY * 0.005);
    const newScale = Math.min(Math.max(scale * zoomFactor, 0.2), 5);
    panX = mx - (mx - panX) * (newScale / scale);
    panY = my - (my - panY) * (newScale / scale);
    scale = newScale;
  } else {
    panX -= e.shiftKey ? 0 : e.deltaX;
    panY -= e.shiftKey ? e.deltaX : e.deltaY;

    if (!e.shiftKey && e.deltaX !== 0) {
        panX -= e.deltaX;
    }
  }
}, { passive: false });

canvas.addEventListener('pointerdown', e => {
  targetPanX = null;
  targetPanY = null;
  activePointers.set(e.pointerId, e);
  const rect = canvas.getBoundingClientRect();
  const rawX = e.clientX - rect.left, rawY = e.clientY - rect.top;
  const { x: mx, y: my } = screenToWorld(rawX, rawY);

  if (activePointers.size === 2) {
    const pts = Array.from(activePointers.values());
    initialPinchDist = Math.hypot(pts[0].clientX - pts[1].clientX, pts[0].clientY - pts[1].clientY);
    initialPinchScale = scale;
    dragging = -1; lasso = null; isPanning = false;
    return;
  }

  if (e.shiftKey || e.button === 1) {
    isPanning = true;
    lastPanX = rawX; lastPanY = rawY;
    canvas.style.cursor = 'grabbing';
    return;
  }

  let hit = -1;
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    if (mx >= n.x-n.w/2 && mx <= n.x+n.w/2 && my >= n.y-n.h/2 && my <= n.y+n.h/2) {
      if (!isNodeVisible(n)) continue;
      hit = i; break;
    }
  }

  const now = Date.now();
  if (hit >= 0 && now - lastClick < 300 && lastClickNode === nodes[hit].id) {
    nodes[hit].collapsed = !nodes[hit].collapsed;
    layout(); rebuildPackets();
    lastClick = 0;
    return;
  }
  if (hit >= 0) {
    lastClick = now;
    lastClickNode = nodes[hit].id;
  }

  if (hit >= 0) {
    if (e.ctrlKey) {
      if (selected.has(hit)) selected.delete(hit);
      else selected.add(hit);
    } else {
      if (!selected.has(hit)) selected = new Set([hit]);
    }
    dragging = hit;
    nodes.forEach((n, i) => {
      n._dragOffX = mx - n.x;
      n._dragOffY = my - n.y;
    });
    canvas.style.cursor = 'grabbing';
  } else {
    selected.clear();
    lasso = { x0: mx, y0: my, x1: mx, y1: my };
    dragging = -1;
  }
});

canvas.addEventListener('pointermove', e => {
  if (activePointers.has(e.pointerId)) activePointers.set(e.pointerId, e);

  const rect = canvas.getBoundingClientRect();
  const rawX = e.clientX - rect.left, rawY = e.clientY - rect.top;

  if (activePointers.size === 2) {
    const pts = Array.from(activePointers.values());
    const dist = Math.hypot(pts[0].clientX - pts[1].clientX, pts[0].clientY - pts[1].clientY);
    if (initialPinchDist > 0) {
      const zoomFactor = dist / initialPinchDist;
      const newScale = Math.min(Math.max(initialPinchScale * zoomFactor, 0.2), 5);
      const cx = (pts[0].clientX + pts[1].clientX) / 2 - rect.left;
      const cy = (pts[0].clientY + pts[1].clientY) / 2 - rect.top;
      panX = cx - (cx - panX) * (newScale / scale);
      panY = cy - (cy - panY) * (newScale / scale);
      scale = newScale;
    }
    return;
  }

  if (isPanning) {
    panX += (rawX - lastPanX);
    panY += (rawY - lastPanY);
    lastPanX = rawX; lastPanY = rawY;
    return;
  }

  const { x: mx, y: my } = screenToWorld(rawX, rawY);

  if (dragging >= 0) {
    selected.forEach(i => {
      nodes[i].x = mx - nodes[i]._dragOffX;
      nodes[i].y = my - nodes[i]._dragOffY;
    });
    rebuildPackets();
    return;
  }

  if (lasso) {
    lasso.x1 = mx; lasso.y1 = my;
    return;
  }

  let found = -1;
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    if (mx >= n.x-n.w/2 && mx <= n.x+n.w/2 && my >= n.y-n.h/2 && my <= n.y+n.h/2) {
      found = i; break;
    }
  }

  if (found !== hovered) {
    hovered = found;
    canvas.style.cursor = hovered >= 0 ? 'grab' : (lasso ? 'crosshair' : 'default');
  }

  if (hovered >= 0) {
    const n = nodes[hovered];
    document.getElementById('tip-name').textContent = n.label;
    let tipType = n.kind.toUpperCase();
    if (n.dnsQueries) tipType += ` • ${n.dnsQueries} DNS`;
    document.getElementById('tip-type').textContent = tipType;
    document.getElementById('tip-ip').textContent = n.ip || '—';
    document.getElementById('tip-dl').textContent = 'RX: ' + fmtSpeed(n.rx);
    document.getElementById('tip-ul').textContent = 'TX: ' + fmtSpeed(n.tx);

    drawSparkline(n.id);
    const tipW = 232, tipH = 135;
    let tx = e.clientX + 20, ty = e.clientY - 20;
    if (tx + tipW > window.innerWidth) tx = e.clientX - tipW - 12;
    if (ty + tipH > window.innerHeight) ty = e.clientY - tipH - 12;
    tip.style.left = tx + 'px'; tip.style.top = ty + 'px';
    tip.classList.add('show');
  } else tip.classList.remove('show');
});

function handlePointerEnd(e) {
  activePointers.delete(e.pointerId);
  if (activePointers.size < 2) initialPinchDist = null;
  if (isPanning) isPanning = false;
  if (dragging >= 0) { savePosAll(); dragging = -1; }
  if (lasso) {
    const lx0 = Math.min(lasso.x0, lasso.x1), lx1 = Math.max(lasso.x0, lasso.x1);
    const ly0 = Math.min(lasso.y0, lasso.y1), ly1 = Math.max(lasso.y0, lasso.y1);
    nodes.forEach((n, i) => {
      if (n.x === undefined) return;
      const nx = n.x - n.w/2, ny = n.y - n.h/2;
      if (nx < lx1 && nx+n.w > lx0 && ny < ly1 && ny+n.h > ly0) selected.add(i);
    });
    lasso = null;
  }
}

canvas.addEventListener('pointerup', handlePointerEnd);
canvas.addEventListener('pointercancel', handlePointerEnd);

function init() {
  setTrafficPeriod(currentTrafficPeriod);
  resize();
  nodes = DEFAULTS.map(d => ({ ...d, rx:0, tx:0, tRx:0, tTx:0, w:180, h:60 }));
  _lastNodeIds = nodes.map(n => n.id).sort().join(',');
  layout();
  rebuildPackets();
  fpsT0 = performance.now();
  render(fpsT0);
  connectSSE();

  const searchInput = document.getElementById('node-search');
  searchInput.addEventListener('input', (e) => {
    searchQuery = e.target.value.toLowerCase().trim();

    if (searchQuery) {
      const matchedNode = nodes.find(n =>
        isNodeVisible(n) && n.x !== undefined &&
        (n.label.toLowerCase().includes(searchQuery) ||
         n.sub.toLowerCase().includes(searchQuery) ||
         (n.ip && n.ip.toLowerCase().includes(searchQuery)))
      );
      if (matchedNode) {
        targetPanX = width / 2 - matchedNode.x * scale;
        targetPanY = height / 2 - matchedNode.y * scale;
      }
    }
  });
}

init();
