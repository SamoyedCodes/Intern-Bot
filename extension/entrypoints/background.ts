export default defineBackground(() => {
  chrome.runtime.onInstalled.addListener(() => {
    chrome.storage.local.set({
      internBotInstallState: {
        installedAt: new Date().toISOString(),
        schemaVersion: 1,
      },
    });
  });
});
