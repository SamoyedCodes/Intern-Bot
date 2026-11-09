// Only local scene assets and this display-only bridge are available in the viewport.
new QWebChannel(qt.webChannelTransport, (channel) => {
  const bridge = channel.objects.crew;
  try {
    const scene = makeCrewScene(
      document.getElementById('stage'),
      (id) => bridge.selectRun(id),
      (index) => bridge.inspectStation(index),
    );
    bridge.snapshot.connect((payload) => scene.update(JSON.parse(payload)));
    document.querySelector('canvas').addEventListener('webglcontextlost', () => bridge.available(false));
    bridge.available(true);
  } catch {
    bridge.available(false);
  }
});
