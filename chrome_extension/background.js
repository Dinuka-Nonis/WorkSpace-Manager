/**
 * background.js — WorkSpace Manager Chrome Extension
 *
 * FIX: Removed the automatic tab-push listeners (onCreated, onRemoved,
 * onUpdated) and the 30-second periodic interval.  These were saving ALL open
 * Chrome tabs into the active session on every tab event, which is why the
 * user saw 22 URLs they never explicitly dropped.
 *
 * Tabs are now saved ONLY when:
 *   1. The user explicitly presses "Save tabs" in the popup (force_snapshot).
 *   2. The native host side-channel requests a snapshot (e.g. from launcher).
 *
 * The session-active handshake is kept so the host always knows which session
 * is current; we just no longer auto-dump every open tab into it.
 */

const NATIVE_HOST_ID = "com.workspace.manager";

const RECONNECT_BASE_MS  = 5_000;
const RECONNECT_MAX_MS   = 60_000;
let   reconnectDelay     = RECONNECT_BASE_MS;

let port = null;
let currentSessionId = null;

// ── Native Messaging ─────────────────────────────────────────────────────────

function connectNative() {
  try {
    port = chrome.runtime.connectNative(NATIVE_HOST_ID);

    port.onMessage.addListener((msg) => {
      console.log("[WorkSpace] Native message received:", msg);

      if (msg.type === "session_active") {
        currentSessionId = msg.session_id;
        console.log(`[WorkSpace] Active session: ${currentSessionId}`);
        // NOTE: we no longer call sendTabs() automatically here.
        // Tabs are only pushed on an explicit user action or host request.
      }

      if (msg.type === "request_tabs") {
        // Host-initiated snapshot (side-channel from launcher / picker).
        if (msg.session_id && msg.session_id !== 0) {
          currentSessionId = msg.session_id;
        }
        const targetId = msg.session_id !== undefined ? msg.session_id : currentSessionId;
        sendTabsForSession(targetId);
      }

      if (msg.type === "session_none") {
        currentSessionId = null;
      }
    });

    port.onDisconnect.addListener(() => {
      console.log("[WorkSpace] Native host disconnected:", chrome.runtime.lastError?.message);
      port = null;
      currentSessionId = null;
      setTimeout(connectNative, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
    });

    reconnectDelay = RECONNECT_BASE_MS;
    console.log("[WorkSpace] Connected to native host.");
    sendMessage({ type: "get_active_session" });

  } catch (err) {
    console.error("[WorkSpace] Native connect failed:", err);
    setTimeout(connectNative, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
  }
}

function sendMessage(msg) {
  if (port) {
    try {
      port.postMessage(msg);
    } catch (err) {
      console.error("[WorkSpace] Send failed:", err);
      port = null;
    }
  }
}

// ── Tab Collection ────────────────────────────────────────────────────────────

async function getCurrentTabs() {
  return new Promise((resolve) => {
    chrome.tabs.query({}, (tabs) => {
      const filtered = tabs
        .filter(t => t.url && !t.url.startsWith("chrome://") && !t.url.startsWith("about:"))
        .map(t => ({
          id: t.id,
          title: t.title || "",
          url: t.url || "",
          favIconUrl: t.favIconUrl || "",
          windowId: t.windowId,
          active: t.active,
          pinned: t.pinned,
        }));
      resolve(filtered);
    });
  });
}

async function sendTabs() {
  if (!currentSessionId) return;
  await sendTabsForSession(currentSessionId);
}

async function sendTabsForSession(sessionId) {
  if (!sessionId && sessionId !== 0) return;

  const tabs = await getCurrentTabs();
  sendMessage({
    type: "tabs_snapshot",
    session_id: sessionId,
    tabs: tabs,
    timestamp: new Date().toISOString(),
  });

  console.log(`[WorkSpace] Sent ${tabs.length} tabs for session ${sessionId}`);
}

// ── Event Listeners ───────────────────────────────────────────────────────────

// REMOVED: chrome.tabs.onCreated / onRemoved / onUpdated listeners.
// Those were the source of the "22 URLs" problem — every tab change
// was triggering a full dump of all open tabs into the active session.

// Popup / content script messages
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "get_session_status") {
    sendResponse({
      connected: port !== null,
      session_id: currentSessionId,
    });
  }

  if (msg.type === "force_snapshot") {
    // Explicit user-initiated save from the popup.
    sendTabs().then(() => sendResponse({ ok: true }));
    return true; // async
  }

  if (msg.type === "session_selected") {
    currentSessionId = msg.session_id;
    sendMessage({ type: "set_active_session", session_id: msg.session_id });
    // Do NOT auto-push tabs here — let the user trigger that explicitly.
    sendResponse({ ok: true });
  }
});

// ── Init ──────────────────────────────────────────────────────────────────────

connectNative();

// REMOVED: startInterval() / setInterval(sendTabs, SEND_INTERVAL_MS)
// Periodic background dumps were silently inflating session URL counts.
