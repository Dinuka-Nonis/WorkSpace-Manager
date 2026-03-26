/**
 * background.js — WorkSpace Manager Chrome Extension
 * Service worker that:
 *  1. Communicates with the native host (Python) via Native Messaging
 *  2. Sends current tabs when requested or on interval
 *  3. Receives session info from the native host
 */

const NATIVE_HOST_ID = "com.workspace.manager";
const SEND_INTERVAL_MS = 30_000; // Push tabs every 30s

// Reconnect backoff: starts at 5s, doubles each attempt, caps at 60s.
const RECONNECT_BASE_MS  = 5_000;
const RECONNECT_MAX_MS   = 60_000;
let   reconnectDelay     = RECONNECT_BASE_MS;

let port = null;
let currentSessionId = null;
let intervalTimer = null;

// ── Native Messaging ─────────────────────────────────────────────────────────

function connectNative() {
  try {
    port = chrome.runtime.connectNative(NATIVE_HOST_ID);

    port.onMessage.addListener((msg) => {
      console.log("[WorkSpace] Native message received:", msg);

      // Native host tells us which session is active
      if (msg.type === "session_active") {
        currentSessionId = msg.session_id;
        console.log(`[WorkSpace] Active session: ${currentSessionId}`);
        // Immediately send current tabs
        sendTabs();
      }

      // Native host requests tabs snapshot
      if (msg.type === "request_tabs") {
        // Always honour the session_id from the request — don't rely on
        // currentSessionId which may be null if the host just started.
        if (msg.session_id) {
          currentSessionId = msg.session_id;
        }
        // Send tabs even for the prewarm ping (session_id === 0) so the
        // host process stays alive and ready for the real request.
        sendTabsForSession(msg.session_id || currentSessionId);
      }

      // Native host says no active session
      if (msg.type === "session_none") {
        currentSessionId = null;
      }
    });

    port.onDisconnect.addListener(() => {
      console.log("[WorkSpace] Native host disconnected:", chrome.runtime.lastError?.message);
      port = null;
      currentSessionId = null;
      // Exponential backoff so a crashed host isn't hammered every 5s.
      setTimeout(connectNative, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
    });

    // Reset backoff — we have a working connection.
    reconnectDelay = RECONNECT_BASE_MS;
    console.log("[WorkSpace] Connected to native host.");
    // Ask which session is currently active
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

// Send tabs when a tab is created / closed / navigated
chrome.tabs.onCreated.addListener(() => sendTabs());
chrome.tabs.onRemoved.addListener(() => sendTabs());
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "complete") {
    sendTabs();
  }
});

// Popup / content script messages
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "get_session_status") {
    sendResponse({
      connected: port !== null,
      session_id: currentSessionId,
    });
  }

  if (msg.type === "force_snapshot") {
    sendTabs().then(() => sendResponse({ ok: true }));
    return true; // async
  }

  if (msg.type === "session_selected") {
    // User picked a session from popup
    currentSessionId = msg.session_id;
    sendMessage({ type: "set_active_session", session_id: msg.session_id });
    sendTabs();
    sendResponse({ ok: true });
  }
});

// ── Periodic push ─────────────────────────────────────────────────────────────

function startInterval() {
  if (intervalTimer) clearInterval(intervalTimer);
  intervalTimer = setInterval(sendTabs, SEND_INTERVAL_MS);
}

// ── Init ──────────────────────────────────────────────────────────────────────

connectNative();
startInterval();
