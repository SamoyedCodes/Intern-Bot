export function scanVisibleFields(root = document) {
  const candidates = Array.from(root.querySelectorAll([
    "input",
    "textarea",
    "select",
    "[contenteditable='true']",
    "[role='combobox']",
    "[role='textbox']",
  ].join(",")));

  const hasPasswordField = candidates.some((element) => {
    return isVisible(element) && String(element.getAttribute("type") || "").toLowerCase() === "password";
  });

  return candidates
    .filter((element) => isFillable(element))
    .map((element) => describeField(element, { hasPasswordField }))
    .filter(Boolean);
}

export function describeField(element, pageHints = {}) {
  const selector = buildSelector(element);
  if (!selector) {
    return null;
  }

  return {
    selector,
    tagName: element.tagName,
    type: String(element.getAttribute("type") || element.getAttribute("role") || "").toLowerCase(),
    role: element.getAttribute("role") || "",
    id: element.id || "",
    name: element.getAttribute("name") || "",
    label: getLabelText(element),
    ariaLabel: element.getAttribute("aria-label") || "",
    placeholder: element.getAttribute("placeholder") || "",
    nearbyText: getNearbyText(element),
    required: element.required || element.getAttribute("aria-required") === "true",
    value: getElementValue(element),
    pageHints,
  };
}

export function isFillable(element) {
  if (!isVisible(element) || element.disabled || element.readOnly) {
    return false;
  }

  const type = String(element.getAttribute("type") || "").toLowerCase();
  return !["hidden", "submit", "button", "reset", "image", "file"].includes(type);
}

export function isVisible(element) {
  const style = window.getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  return style.visibility !== "hidden"
    && style.display !== "none"
    && rect.width > 0
    && rect.height > 0;
}

function getElementValue(element) {
  if ("value" in element) {
    return element.value || "";
  }
  return element.textContent || "";
}

function getLabelText(element) {
  const labels = [];
  if (element.id) {
    labels.push(...Array.from(document.querySelectorAll(`label[for="${cssEscape(element.id)}"]`)));
  }
  if (element.labels) {
    labels.push(...Array.from(element.labels));
  }
  const closestLabel = element.closest("label");
  if (closestLabel) {
    labels.push(closestLabel);
  }
  const labelledBy = element.getAttribute("aria-labelledby");
  if (labelledBy) {
    for (const id of labelledBy.split(/\s+/)) {
      const labelElement = document.getElementById(id);
      if (labelElement) {
        labels.push(labelElement);
      }
    }
  }
  return uniqueText(labels.map((label) => label.textContent));
}

function getNearbyText(element) {
  const parts = [];
  const container = element.closest("[data-automation-id], [role='group'], fieldset, div, li, section");
  if (container) {
    parts.push(container.textContent || "");
  }
  const previous = element.previousElementSibling;
  if (previous) {
    parts.push(previous.textContent || "");
  }
  return uniqueText(parts).slice(0, 500);
}

function uniqueText(values) {
  return Array.from(new Set(values.map((value) => String(value || "").replace(/\s+/g, " ").trim()).filter(Boolean))).join(" ");
}

export function buildSelector(element) {
  if (element.id) {
    return `#${cssEscape(element.id)}`;
  }

  const dataId = element.getAttribute("data-automation-id");
  if (dataId) {
    return `${element.tagName.toLowerCase()}[data-automation-id="${cssEscapeAttribute(dataId)}"]`;
  }

  const name = element.getAttribute("name");
  if (name) {
    return `${element.tagName.toLowerCase()}[name="${cssEscapeAttribute(name)}"]`;
  }

  const path = [];
  let current = element;
  while (current && current.nodeType === Node.ELEMENT_NODE && current !== document.body) {
    const tag = current.tagName.toLowerCase();
    const parent = current.parentElement;
    if (!parent) {
      break;
    }
    const siblings = Array.from(parent.children).filter((child) => child.tagName === current.tagName);
    const index = siblings.indexOf(current) + 1;
    path.unshift(`${tag}:nth-of-type(${index})`);
    current = parent;
  }
  return path.length ? `body > ${path.join(" > ")}` : "";
}

function cssEscape(value) {
  return window.CSS?.escape ? window.CSS.escape(value) : String(value).replace(/["\\#.:()[\]\s]/g, "\\$&");
}

function cssEscapeAttribute(value) {
  return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}
