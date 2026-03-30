/**
 * background.js — WorkSpace Manager Chrome Extension
 *
 * Tab-save policy (strict):
 *   • Tabs are ONLY saved when the user explicitly clicks "Save tabs" in the
 *     popup, which sends a force_snapshot message.
 *   • The native host may still ask for the ACTIVE tab via request_tabs, but
 *     ONLY for drag-drop capture (all_tabs=false means one tab, triggered by
 *     the Python side after a confirmed drop-zone event).
 *   • Connecting / getting the active session NEVER auto-sends tabs.
 *   • No periodic interval, no onCreated/onRemoved/onUpdated listeners.
 *
 * Profile detection:
 *   • getProfileInfo() uses chrome.identity to get the signed-in email AND
 *     reads the profile directory name from the extension's own storage key
 *     (set by the native host after it confirms the profile mapping).
 *   • Every tab snapshot includes profile_email so the native host can do
 *     an authoritative Local State lookup on its side.
 */

const NATIVE_HOST_ID = "com.workspace.manager";

const RECONNECT_BASE_MS = 5_000;
const RECONNECT_MAX_MS  = 60_000;
let   reconnectDelay    = RECONNECT_BASE_MS;

let port            = null;
let currentSessionId = null;

// ── Native Messaging ──────────────────────────────────────────────────────────

function connectNative() {
  try {
    port = chrome.runtime.connectNative(NATIVE_HOST_ID);

    port.onMessage.addListener((msg) => {
      console.log("[WorkSpace] Native message received:", msg);

      if (msg.type === "session_active") {
        currentSessionId = msg.session_id;
        console.log(`[WorkSpace] Active session set: ${currentSessionId}`);
        // DO NOT auto-send tabs here. Session becoming active ≠ user wants
        // all open tabs saved.
      }

      if (msg.type === "sessions_list") {
        chrome.storage.local.set({ sessions: msg.sessions || [] });
        console.log(`[WorkSpace] Cached ${(msg.sessions || []).length} sessions`);
      }

      if (msg.type === "request_tabs") {
        // Host-initiated request — ONLY for drag-drop (all_tabs must be false).
        // If all_tabs is true here it means a force_snapshot from the popup
        // already handled it; ignore duplicate requests.
        if (msg.session_id && msg.session_id !== 0) {
          currentSessionId = msg.session_id;
        }
        const targetId = msg.session_id !== undefined ? msg.session_id : currentSessionId;
        const allTabs  = msg.all_tabs === true;

        if (allTabs) {
          // Explicit bulk save — only happens via force_snapshot popup button.
          // If the host somehow sends all_tabs=true here, honour it (user action).
          sendTabsForSession(targetId, true);
        } else {
          // Drag-drop: send ONLY the active focused tab.
          sendTabsForSession(targetId, false);
        }
      }

      if (msg.type === "session_none") {
        currentSessionId = null;
      }

      // Native host confirms which profile directory this Chrome instance uses.
      // Store it so getProfileInfo() can return it reliably.
      if (msg.type === "profile_confirmed") {
        if (msg.profile_dir) {
          chrome.storage.local.set({
            confirmed_profile_dir:  msg.profile_dir,
            confirmed_profile_name: msg.profile_name || "",
          });
          console.log(`[WorkSpace] Profile confirmed: ${msg.profile_dir} (${msg.profile_name})`);
        }
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
    sendMessage({ type: "get_sessions" });

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

// ── Profile Detection ─────────────────────────────────────────────────────────

/**
 * Returns the best available profile info for this Chrome instance.
 *
 * Priority:
 *   1. confirmed_profile_dir — set by the native host after authoritative
 *      Local State lookup. This is the MOST reliable source.
 *   2. chrome.identity email — the signed-in Google account email. Sent to
 *      the host so it can do a Local State lookup and send back a
 *      profile_confirmed message.
 *   3. Empty strings — host will try process-tree detection as last resort.
 */
async function getProfileInfo() {
  // Check if the host has already confirmed the profile dir for this instance.
  const stored = await new Promise((resolve) => {
    chrome.storage.local.get(
      ["confirmed_profile_dir", "confirmed_profile_name"],
      (items) => resolve(items || {})
    );
  });

  const confirmedDir  = stored.confirmed_profile_dir  || "";
  const confirmedName = stored.confirmed_profile_name || "";

  // Always include the identity email as a hint for the host.
  const identityInfo = await new Promise((resolve) => {
    if (chrome.identity && chrome.identity.getProfileUserInfo) {
      chrome.identity.getProfileUserInfo({ accountStatus: "ANY" }, (info) => {
        if (chrome.runtime.lastError) {
          resolve({ email: "" });
          return;
        }
        resolve({ email: info?.email || "" });
      });
    } else {
      resolve({ email: "" });
    }
  });

  return {
    profile_dir:   confirmedDir,
    profile_name:  confirmedName,
    profile_email: identityInfo.email,
    // hint for the host to do a Local State lookup if profile_dir is empty
    profile_hint:  identityInfo.email,
  };
}

// ── Tab Collection ─────────────────────────────────────────────────────────────

async function getCurrentTabs() {
  const profileInfo = await getProfileInfo();
  return new Promise((resolve) => {
    chrome.tabs.query({}, (tabs) => {
      const filtered = tabs
        .filter(t => t.url && !t.url.startsWith("chrome://") && !t.url.startsWith("about:"))
        .map(t => ({
          id:            t.id,
          title:         t.title || "",
          url:           t.url   || "",
          favIconUrl:    t.favIconUrl || "",
          windowId:      t.windowId,
          active:        t.active,
          pinned:        t.pinned,
          profile_dir:   profileInfo.profile_dir,
          profile_name:  profileInfo.profile_name,
          profile_email: profileInfo.profile_email,
          profile_hint:  profileInfo.profile_hint,
        }));
      resolve(filtered);
    });
  });
}

/**
 * Get only the single active tab in the focused window.
 * Used for drag-drop: we want EXACTLY the tab the user is dragging,
 * not all background tabs.
 */
async function getActiveFocusedTab() {
  const profileInfo = await getProfileInfo();
  return new Promise((resolve) => {
    chrome.tabs.query({ active: true, lastFocusedWindow: true }, (tabs) => {
      if (!tabs || tabs.length === 0) { resolve(null); return; }
      const t = tabs[0];
      if (!t.url || t.url.startsWith("chrome://") || t.url.startsWith("about:")) {
        resolve(null); return;
      }
      resolve({
        id:            t.id,
        title:         t.title || "",
        url:           t.url   || "",
        favIconUrl:    t.favIconUrl || "",
        windowId:      t.windowId,
        active:        true,
        pinned:        t.pinned,
        profile_dir:   profileInfo.profile_dir,
        profile_name:  profileInfo.profile_name,
        profile_email: profileInfo.profile_email,
        profile_hint:  profileInfo.profile_hint,
      });
    });
  });
}

async function sendTabs() {
  if (!currentSessionId) return;
  await sendTabsForSession(currentSessionId, true);
}

/**
 * @param {number|null} sessionId
 * @param {boolean} allTabs  true=all tabs (explicit save), false=active tab only (drag-drop)
 */
async function sendTabsForSession(sessionId, allTabs = false) {
  if (!sessionId && sessionId !== 0) return;

  let tabs;
  if (allTabs) {
    tabs = await getCurrentTabs();
  } else {
    const active = await getActiveFocusedTab();
    tabs = active ? [active] : [];
  }

  if (tabs.length === 0) {
    console.log(`[WorkSpace] No tabs to send for session ${sessionId}`);
    return;
  }

  sendMessage({
    type:       "tabs_snapshot",
    session_id: sessionId,
    tabs:       tabs,
    timestamp:  new Date().toISOString(),
    all_tabs:   allTabs,
  });

  console.log(`[WorkSpace] Sent ${tabs.length} tab(s) to session ${sessionId} (allTabs=${allTabs})`);
}

// ── Event Listeners ───────────────────────────────────────────────────────────

// NO onCreated / onRemoved / onUpdated — those cause auto-save on tab open.

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  if (msg.type === "get_session_status") {
    sendResponse({ connected: port !== null, session_id: currentSessionId });
  }

  if (msg.type === "force_snapshot") {
    // Explicit user action from popup — save all open tabs.
    sendTabs().then(() => {
      sendMessage({ type: "get_sessions" });
      sendResponse({ ok: true });
    });
    return true; // async
  }

  if (msg.type === "session_selected") {
    currentSessionId = msg.session_id;
    sendMessage({ type: "set_active_session", session_id: msg.session_id });
    sendMessage({ type: "get_sessions" });
    sendResponse({ ok: true });
  }

  // Popup requests the current profile info (for display / debug).
  if (msg.type === "get_profile_info") {
    getProfileInfo().then((info) => sendResponse(info));
    return true; // async
  }
});

// ── Init ──────────────────────────────────────────────────────────────────────

connectNative();
