import { mapFieldToAnswer } from "../src/fill/fieldMapping.js";
import { scanVisibleFields } from "../src/fill/domScanner.js";

type FillResult = {
  scanned: number;
  filled: number;
  skipped: number;
  missingProfile: boolean;
};

type StoredProfile = {
  internBotProfile?: Record<string, unknown>;
};

export default defineContentScript({
  matches: ["*://*.myworkdayjobs.com/*", "*://*.myworkday.com/*"],
  runAt: "document_idle",
  main() {
    installPageBridge();
    installStatusStyles();
    observePage();

    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (message?.type !== "intern-bot:fill-visible") {
        return false;
      }

      fillVisibleFields()
        .then(sendResponse)
        .catch((error) => {
          sendResponse({
            scanned: 0,
            filled: 0,
            skipped: 0,
            missingProfile: false,
            error: error instanceof Error ? error.message : String(error),
          });
        });
      return true;
    });
  },
});

async function fillVisibleFields(): Promise<FillResult> {
  const profile = await loadProfile();
  if (!profile) {
    return { scanned: 0, filled: 0, skipped: 0, missingProfile: true };
  }

  const fields = scanVisibleFields();
  let filled = 0;
  let skipped = 0;

  for (const field of fields) {
    if (!field) {
      continue;
    }

    clearFieldState(field.selector);

    if (String(field.value || "").trim()) {
      skipped += 1;
      markField(field.selector, "skipped");
      continue;
    }

    const answer = mapFieldToAnswer(field, profile, window.location.host);
    if (!answer) {
      skipped += 1;
      markField(field.selector, "needs-review");
      continue;
    }

    const result = await setFieldInPage(field.selector, answer.value);
    if (result.ok) {
      filled += 1;
      markField(field.selector, "filled");
    } else {
      skipped += 1;
      markField(field.selector, "needs-review");
    }
  }

  return { scanned: fields.length, filled, skipped, missingProfile: false };
}

async function loadProfile(): Promise<Record<string, unknown> | null> {
  const stored = await chrome.storage.local.get("internBotProfile") as StoredProfile;
  return stored.internBotProfile || null;
}

function installPageBridge() {
  if (document.documentElement.dataset.internBotBridge === "installed") {
    return;
  }
  document.documentElement.dataset.internBotBridge = "installed";
  const script = document.createElement("script");
  script.src = chrome.runtime.getURL("page-bridge.js");
  script.async = false;
  script.addEventListener("load", () => script.remove(), { once: true });
  (document.head || document.documentElement).appendChild(script);
}

function setFieldInPage(selector: string, value: unknown): Promise<{ ok: boolean; error?: string }> {
  const requestId = crypto.randomUUID();

  return new Promise((resolve) => {
    const timeout = window.setTimeout(() => {
      window.removeEventListener("message", onMessage);
      resolve({ ok: false, error: "Timed out waiting for page bridge" });
    }, 1200);

    function onMessage(event: MessageEvent) {
      const message = event.data;
      if (
        event.source !== window
        || message?.source !== "intern-bot-page"
        || message?.type !== "set-field-result"
        || message?.requestId !== requestId
      ) {
        return;
      }

      window.clearTimeout(timeout);
      window.removeEventListener("message", onMessage);
      resolve({ ok: Boolean(message.ok), error: message.error });
    }

    window.addEventListener("message", onMessage);
    window.postMessage({
      source: "intern-bot-extension",
      type: "set-field",
      requestId,
      selector,
      value,
    }, "*");
  });
}

function installStatusStyles() {
  if (document.getElementById("intern-bot-autofill-style")) {
    return;
  }
  const style = document.createElement("style");
  style.id = "intern-bot-autofill-style";
  style.textContent = `
    .intern-bot-filled {
      outline: 2px solid #17b978 !important;
      outline-offset: 2px !important;
    }
    .intern-bot-needs-review {
      outline: 2px solid #ffb020 !important;
      outline-offset: 2px !important;
    }
  `;
  document.documentElement.appendChild(style);
}

function clearFieldState(selector: string) {
  const element = document.querySelector(selector);
  element?.classList.remove("intern-bot-filled", "intern-bot-needs-review");
}

function markField(selector: string, state: "filled" | "needs-review" | "skipped") {
  if (state === "skipped") {
    return;
  }
  const element = document.querySelector(selector);
  element?.classList.add(state === "filled" ? "intern-bot-filled" : "intern-bot-needs-review");
}

function observePage() {
  let timeout = 0;
  const observer = new MutationObserver(() => {
    window.clearTimeout(timeout);
    timeout = window.setTimeout(() => {
      try {
        chrome.runtime.sendMessage({
          type: "intern-bot:fields-detected",
          count: scanVisibleFields().length,
        });
      } catch {
        // Popup/background listeners are optional.
      }
    }, 350);
  });

  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
}
