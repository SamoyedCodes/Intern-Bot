chrome.runtime.sendMessage({type: 'wake'}).then(() => window.close()).catch(() => {});
