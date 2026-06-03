(() => {
  if (window.__internBotPageBridgeInstalled) {
    return;
  }
  window.__internBotPageBridgeInstalled = true;

  const valueSetters = new Map([
    ["INPUT", Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set],
    ["TEXTAREA", Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set],
    ["SELECT", Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set],
  ]);

  const checkedSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "checked")?.set;

  function dispatchFormEvents(element) {
    for (const eventName of ["input", "change", "blur"]) {
      element.dispatchEvent(new Event(eventName, { bubbles: true }));
    }
  }

  function setNativeValue(element, value) {
    const setter = valueSetters.get(element.tagName);
    if (setter) {
      setter.call(element, value);
      dispatchFormEvents(element);
      return true;
    }
    if (element.isContentEditable) {
      element.textContent = value;
      dispatchFormEvents(element);
      return true;
    }
    return false;
  }

  function setCheckboxOrRadio(element, value) {
    const shouldCheck = value === true || String(value).toLowerCase() === "true" || String(value).toLowerCase() === "yes";
    if (checkedSetter) {
      checkedSetter.call(element, shouldCheck);
      dispatchFormEvents(element);
      return true;
    }
    element.checked = shouldCheck;
    dispatchFormEvents(element);
    return true;
  }

  function handleSetField(message) {
    const element = document.querySelector(message.selector);
    if (!element) {
      return { ok: false, error: "Element not found" };
    }

    const tagName = element.tagName;
    const type = String(element.getAttribute("type") || "").toLowerCase();

    if (tagName === "INPUT" && ["checkbox", "radio"].includes(type)) {
      return { ok: setCheckboxOrRadio(element, message.value) };
    }

    return { ok: setNativeValue(element, message.value) };
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window) {
      return;
    }

    const message = event.data;
    if (!message || message.source !== "intern-bot-extension" || message.type !== "set-field") {
      return;
    }

    const result = handleSetField(message);
    window.postMessage({
      source: "intern-bot-page",
      type: "set-field-result",
      requestId: message.requestId,
      ...result,
    }, "*");
  });
})();
