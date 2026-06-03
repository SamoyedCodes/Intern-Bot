import "./style.css";

const profileStatus = document.querySelector<HTMLParagraphElement>("#profileStatus")!;
const result = document.querySelector<HTMLParagraphElement>("#result")!;
const profileFile = document.querySelector<HTMLInputElement>("#profileFile")!;
const fillVisible = document.querySelector<HTMLButtonElement>("#fillVisible")!;

void refreshProfileStatus();

profileFile.addEventListener("change", async () => {
  const file = profileFile.files?.[0];
  if (!file) {
    return;
  }

  try {
    const payload = JSON.parse(await file.text());
    const profile = payload.profile || payload;
    await chrome.storage.local.set({
      internBotProfile: profile,
      internBotProfileMeta: {
        importedAt: new Date().toISOString(),
        source: payload.source || "manual-import",
        schemaVersion: payload.schema_version || 0,
      },
    });
    result.textContent = "Profile imported.";
    await refreshProfileStatus();
  } catch (error) {
    result.textContent = `Import failed: ${error instanceof Error ? error.message : String(error)}`;
  } finally {
    profileFile.value = "";
  }
});

fillVisible.addEventListener("click", async () => {
  result.textContent = "Scanning current tab...";
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) {
    result.textContent = "No active tab found.";
    return;
  }

  try {
    const response = await chrome.tabs.sendMessage(tab.id, { type: "intern-bot:fill-visible" });
    if (response?.missingProfile) {
      result.textContent = "Import a profile first.";
      return;
    }
    if (response?.error) {
      result.textContent = response.error;
      return;
    }
    result.textContent = `Scanned ${response.scanned}, filled ${response.filled}, review ${response.skipped}.`;
  } catch {
    result.textContent = "Open a Workday application page, then try again.";
  }
});

async function refreshProfileStatus() {
  const { internBotProfile, internBotProfileMeta } = await chrome.storage.local.get([
    "internBotProfile",
    "internBotProfileMeta",
  ]);
  if (!internBotProfile) {
    profileStatus.textContent = "No profile imported";
    fillVisible.disabled = true;
    return;
  }

  const name = [internBotProfile.first_name, internBotProfile.last_name].filter(Boolean).join(" ");
  const importedAt = internBotProfileMeta?.importedAt ? new Date(internBotProfileMeta.importedAt).toLocaleString() : "";
  profileStatus.textContent = `${name || "Profile"} imported${importedAt ? ` ${importedAt}` : ""}`;
  fillVisible.disabled = false;
}
