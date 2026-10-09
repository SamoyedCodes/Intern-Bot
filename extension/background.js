/* Commands are available only through the worker's Playwright execution context. */
const key = run => `run:${run}`;
async function send(binding, command, payload = {}) {
  const response = await chrome.tabs.sendMessage(binding.tab, {command, payload, token: binding.token, document: binding.document}, {documentId: binding.document});
  if (!response || response.document !== binding.document || response.token !== binding.token) throw Error('Stale application document');
  if (response.error) throw Error(response.error);
  return response;
}
globalThis.internBot = {
  async command({command, run, binding, payload = {}}) {
    if (command === 'discover') {
      const tabs = (await chrome.tabs.query({})).filter(t => t.url === payload.url);
      if (tabs.length !== 1) return {matches: [], problem: 'A unique application tab could not be identified.'};
      const frames = await chrome.webNavigation.getAllFrames({tabId: tabs[0].id});
      const matches = [];
      for (const frame of frames) {
        if (!frame.url.startsWith('https://')) continue;
        try {
          const result = await chrome.tabs.sendMessage(tabs[0].id, {command: 'detect', document: frame.documentId}, {documentId: frame.documentId});
          for (const adapter of result.adapters || []) matches.push({tab: tabs[0].id, frame: frame.frameId, document: frame.documentId, url: frame.url, adapter});
        } catch { /* A loading or inaccessible frame cannot receive personal data. */ }
      }
      return {matches};
    }
    if (command === 'prepare') {
      const previous = (await chrome.storage.session.get(key(run)))[key(run)];
      if (previous) await send(previous, 'stop').catch(() => {});
      binding = {...binding, token: crypto.randomUUID(), run};
      await chrome.storage.session.set({[key(run)]: binding});
      const result = await send(binding, 'prepare', payload);
      return {...result, binding};
    }
    const current = (await chrome.storage.session.get(key(run)))[key(run)];
    if (!current || !binding || current.token !== binding.token || current.document !== binding.document || current.tab !== binding.tab) throw Error('Expired application command');
    return send(current, command, payload);
  }
};
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id === chrome.runtime.id && message.type === 'wake') reply({ready: true});
});
