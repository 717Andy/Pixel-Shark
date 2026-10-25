/* Browser UI for the Pixel Shark table.
 *
 * The server is the source of truth. This file only draws the latest snapshot
 * and posts an action when you click. Skins are local. Card visibility follows
 * the snapshot's hole_cards_shown flag.
 */

const SUITS = { s: "♠", h: "♥", d: "♦", c: "♣" };

const state = {
  tableId: null,
  snapshot: null,
  socket: null,
  lastLog: "",
  lastFp: "",
};

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function rankText(code) {
  if (!code) return "";
  return code[0] === "T" ? "10" : code[0];
}

function setSkin(name) {
  const skin = ["felt", "midnight", "broadcast"].includes(name) ? name : "felt";
  document.documentElement.dataset.skin = skin;
  $("skin").value = skin;
  localStorage.setItem("pixelshark-skin", skin);
}

function showError(message) {
  const node = $("error");
  if (!message) {
    node.hidden = true;
    node.textContent = "";
    return;
  }
  node.hidden = false;
  node.textContent = message;
}

function pushLog(line) {
  const item = document.createElement("li");
  item.textContent = line;
  const list = $("log");
  list.prepend(item);
  while (list.children.length > 14) {
    list.removeChild(list.lastChild);
  }
}

function cardHtml(code, shown, where, index, seat) {
  const face = shown && code ? "up" : "down";
  const red = code && (code[1] === "h" || code[1] === "d") ? "red" : "black";
  const seatAttr = seat == null ? "" : ` data-seat="${seat}"`;
  const body = face === "up"
    ? `<span class="rank">${esc(rankText(code))}</span><span class="suit">${SUITS[code[1]] || ""}</span>`
    : `<span class="back-mark"></span>`;
  return `<div class="card ${face} ${red}" data-bbox="card" data-where="${where}" data-index="${index}" data-face="${face}" data-card="${face === "up" ? esc(code) : ""}" data-truth="${esc(code || "")}"${seatAttr}>${body}</div>`;
}

function chipHtml(kind, amount, seat) {
  const seatAttr = seat == null ? "" : ` data-seat="${seat}"`;
  return `<span class="chips ${kind}" data-bbox="chips" data-kind="${kind}" data-amount="${amount}"${seatAttr}><i class="chip-graphic"></i>${amount}</span>`;
}

function fingerprint(snapshot) {
  return JSON.stringify({
    hand: snapshot.hand_id,
    phase: snapshot.hand_phase.value,
    street: snapshot.street.value,
    actor: snapshot.actor_seat.value,
    pot: snapshot.total_pot.value,
    board: snapshot.board.map((card) => card.value),
    seats: snapshot.seats.map((seat) => [seat.stack.value, seat.bet.value, seat.status.value, seat.hole_cards_shown.value]),
    actions: snapshot.legal_actions.map((action) => action.kind),
    hero: snapshot.hero_seat,
    reveal: snapshot.reveal,
    autoplay: snapshot.autoplay,
  });
}

function render(snapshot) {
  document.body.dataset.handId = snapshot.hand_id;
  document.body.dataset.ready = "true";
  const street = snapshot.street.value;
  const phase = snapshot.hand_phase.value;
  const actor = snapshot.seats.find((seat) => seat.seat === snapshot.actor_seat.value);
  const actorName = phase === "complete" ? "Hand complete" : actor ? `${actor.name.value} to act` : "Dealing";
  $("status").textContent = `Hand ${snapshot.hand_number.value} · ${street} · ${actorName} · blinds ${snapshot.small_blind.value}/${snapshot.big_blind.value}`;
  $("reveal").value = snapshot.reveal;
  $("play").textContent = snapshot.hero_seat == null ? "Play seat 1" : "Watch bots";
  $("autoplay").textContent = snapshot.autoplay ? "Pause bots" : "Resume bots";

  const board = snapshot.board.map((card, index) => cardHtml(card.value, true, "board", index, null));
  while (board.length < 5) {
    board.push(`<div class="card slot" data-index="${board.length}"></div>`);
  }
  $("board").innerHTML = board.join("");
  $("pot").innerHTML = `<div class="pot">${chipHtml("pot", snapshot.total_pot.value, null)} pot</div>`;

  const wide = window.innerWidth >= 800;
  const rx = wide ? 40 : 34;
  const ry = wide ? 38 : 33;
  const count = snapshot.seats.length;
  $("seats").innerHTML = snapshot.seats.map((seat) => {
    const angle = Math.PI / 2 + (seat.seat / count) * Math.PI * 2;
    const left = 50 + Math.cos(angle) * rx;
    const top = 50 + Math.sin(angle) * ry;
    const cards = seat.hole_cards.length
      ? seat.hole_cards.map((card, index) => cardHtml(
          card.value,
          seat.hole_cards_shown.value,
          "hole",
          index,
          seat.seat,
        )).join("")
      : "";
    const dealer = seat.is_button.value
      ? `<span class="dealer" data-bbox="button" data-kind="dealer" data-action="dealer" data-seat="${seat.seat}">D</span>`
      : "";
    const bet = seat.bet.value > 0 ? `<div class="bet">${chipHtml("bet", seat.bet.value, seat.seat)}</div>` : `<div class="bet"></div>`;
    const classes = [
      "seat",
      seat.is_actor.value ? "actor" : "",
      seat.seat === snapshot.hero_seat ? "hero" : "",
      seat.status.value === "folded" ? "folded" : "",
    ].filter(Boolean).join(" ");
    const position = seat.position.value || seat.status.value;
    return `<div class="${classes}" data-seat="${seat.seat}" style="left:${left}%;top:${top}%">
      <div class="seat-cards">${cards}</div>
      ${bet}
      <div class="plate">
        ${dealer}
        <div class="seat-name">${esc(seat.name.value)}</div>
        <div class="seat-meta">${esc(position)} · ${chipHtml("stack", seat.stack.value, seat.seat)}</div>
      </div>
    </div>`;
  }).join("");

  renderActions(snapshot);
}

function renderActions(snapshot) {
  const yours = snapshot.hero_seat != null && snapshot.actor_seat.value === snapshot.hero_seat && snapshot.hand_phase.value === "betting";
  const buttons = snapshot.legal_actions.map((action) => {
    if (action.kind === "fold" || action.kind === "check") {
      const label = action.kind === "fold" ? "Fold" : "Check";
      return actionButton(action.kind, label, yours, null);
    }
    if (action.kind === "call") {
      const amount = action.amount ? action.amount.value : 0;
      const label = action.is_all_in ? `Call ${amount} all-in` : `Call ${amount}`;
      return actionButton("call", label, yours, null);
    }
    return (action.sizing || []).map((option) => {
      const amount = option.to_amount.value;
      const label = option.label === "all-in" ? `All-in ${amount}` : `${option.label} ${amount}`;
      return actionButton(action.kind, label, yours, amount);
    }).join("");
  }).join("");

  let custom = "";
  const aggressive = snapshot.legal_actions.find((action) => action.kind === "bet" || action.kind === "raise");
  if (yours && aggressive && aggressive.min_to && aggressive.max_to) {
    custom = `<form class="raise-box" id="raise-form">
      <input id="raise-to" type="number" min="${aggressive.min_to.value}" max="${aggressive.max_to.value}" step="1" value="${aggressive.min_to.value}" aria-label="Raise to" />
      <button class="action" type="submit" data-bbox="button" data-kind="action" data-action="${aggressive.kind}" data-enabled="true" id="raise-custom">${aggressive.kind === "bet" ? "Bet" : "Raise"} to</button>
    </form>`;
  }

  const note = snapshot.hand_phase.value === "complete"
    ? (snapshot.autoplay ? "Next hand in a moment." : "Hand complete.")
    : (yours ? "Your turn. F folds, C checks or calls." : "Action buttons light up on your turn.");
  $("actions").innerHTML = `${buttons}${custom}<span class="seat-meta">${esc(note)}</span>`;

  $("actions").querySelectorAll("button[data-action]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.id === "raise-custom") return;
      sendAction(button.dataset.action, button.dataset.to ? Number(button.dataset.to) : null);
    });
  });
  const form = $("raise-form");
  if (form) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const input = $("raise-to");
      const kind = $("raise-custom").dataset.action;
      sendAction(kind, Number(input.value));
    });
  }
}

function actionButton(kind, label, enabled, toAmount) {
  const toAttr = toAmount == null ? "" : ` data-to="${toAmount}"`;
  return `<button type="button" class="action" data-bbox="button" data-kind="action" data-action="${kind}" data-enabled="${enabled ? "true" : "false"}"${toAttr} ${enabled ? "" : "disabled"}>${esc(label)}</button>`;
}

function onSnapshot(snapshot) {
  state.snapshot = snapshot;
  if (snapshot.last_action && snapshot.last_action !== state.lastLog) {
    pushLog(snapshot.last_action);
    state.lastLog = snapshot.last_action;
  }
  const fp = fingerprint(snapshot);
  if (fp === state.lastFp) return;
  state.lastFp = fp;
  render(snapshot);
}

async function sendAction(kind, toAmount) {
  const snapshot = state.snapshot;
  if (!snapshot || snapshot.hero_seat == null) return;
  showError("");
  const response = await fetch(`/api/tables/${state.tableId}/actions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seat: snapshot.hero_seat, kind, to_amount: toAmount }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    showError(body.detail || "That action was not accepted.");
    return;
  }
  onSnapshot(await response.json());
}

function connect(tableId) {
  state.tableId = tableId;
  if (state.socket) state.socket.close();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${proto}://${location.host}/api/tables/${tableId}/ws`);
  state.socket = socket;
  socket.addEventListener("message", (event) => {
    showError("");
    onSnapshot(JSON.parse(event.data));
  });
  socket.addEventListener("close", () => {
    if (state.socket !== socket) return;
    window.setTimeout(() => connect(tableId), 1000);
  });
}

async function postJson(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    showError(payload.detail || "Request failed.");
    return;
  }
  onSnapshot(await response.json());
}

$("skin").addEventListener("change", () => setSkin($("skin").value));
$("reveal").addEventListener("change", () => {
  if (!state.tableId) return;
  postJson(`/api/tables/${state.tableId}/reveal`, { mode: $("reveal").value });
});
$("play").addEventListener("click", () => {
  if (!state.snapshot) return;
  const seat = state.snapshot.hero_seat == null ? 0 : null;
  postJson(`/api/tables/${state.tableId}/hero`, { seat });
});
$("autoplay").addEventListener("click", () => {
  if (!state.snapshot) return;
  postJson(`/api/tables/${state.tableId}/autoplay`, { enabled: !state.snapshot.autoplay });
});

window.addEventListener("keydown", (event) => {
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
  const key = event.key.toLowerCase();
  if (key === "f") clickKind("fold");
  if (key === "c") clickKind("check") || clickKind("call");
});

function clickKind(kind) {
  const button = document.querySelector(`#actions button[data-action="${kind}"]:not(:disabled)`);
  if (!button) return false;
  button.click();
  return true;
}

async function boot() {
  const params = new URLSearchParams(location.search);
  setSkin(params.get("skin") || localStorage.getItem("pixelshark-skin") || "felt");
  try {
    let tableId = params.get("table");
    if (!tableId) {
      const session = await fetch("/api/session");
      if (!session.ok) throw new Error("No table is running.");
      tableId = (await session.json()).table_id;
    }
    const existing = await fetch(`/api/tables/${tableId}/state`);
    if (!existing.ok) throw new Error(`Table ${tableId} was not found.`);
    onSnapshot(await existing.json());
    connect(tableId);
  } catch (error) {
    showError(error.message || "Could not reach the table.");
  }
}

boot();
