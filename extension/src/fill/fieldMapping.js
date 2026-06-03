const FIELD_DEFINITIONS = [
  { key: "first_name", labels: ["first name", "given name", "legal first"] },
  { key: "last_name", labels: ["last name", "family name", "surname", "legal last"] },
  { key: "email", labels: ["email", "e-mail"] },
  { key: "phone", labels: ["phone", "mobile", "telephone"] },
  { key: "address", labels: ["address", "location", "city", "country", "region"] },
  { key: "linkedin_url", labels: ["linkedin"] },
  { key: "github_url", labels: ["github"] },
  { key: "portfolio_url", labels: ["portfolio", "website", "personal site"] },
  { key: "school", labels: ["school", "university", "institution", "college"] },
  { key: "degree", labels: ["degree"] },
  { key: "major", labels: ["major", "field of study", "discipline"] },
  { key: "graduation", labels: ["graduation", "graduate", "completion date"] },
];

const NEGATIVE_LABELS = [
  "search",
  "captcha",
  "verification",
  "one-time",
  "security code",
];

export function normalizeText(value) {
  return String(value || "")
    .replace(/[*:]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

export function parseDefaultAnswers(defaultAnswers) {
  const answers = [];
  for (const line of String(defaultAnswers || "").split(/\r?\n/)) {
    const match = line.match(/^(.+?)\s*:\s*(.+)$/);
    if (!match) {
      continue;
    }
    answers.push({
      label: normalizeText(match[1]),
      value: match[2].trim(),
    });
  }
  return answers;
}

export function getCredentialForHost(profile, host) {
  const credentials = profile?.workday_credentials || {};
  const normalizedHost = normalizeHost(host);
  return credentials[normalizedHost] || credentials[`https://${normalizedHost}`] || {};
}

export function normalizeHost(host) {
  return String(host || "")
    .replace(/^https?:\/\//, "")
    .split("/")[0]
    .replace(/^www\./, "")
    .toLowerCase();
}

export function buildFieldText(field) {
  return normalizeText([
    field.label,
    field.ariaLabel,
    field.placeholder,
    field.name,
    field.id,
    field.nearbyText,
  ].filter(Boolean).join(" "));
}

export function mapFieldToAnswer(field, profile, pageHost = "") {
  const fieldText = buildFieldText(field);
  if (!fieldText || NEGATIVE_LABELS.some((label) => fieldText.includes(label))) {
    return null;
  }

  const type = normalizeText(field.type);
  const credential = getCredentialForHost(profile, pageHost);
  const hasPasswordOnPage = Boolean(field.pageHints?.hasPasswordField);

  if (type === "password" && credential.password) {
    return answer("workday_credential.password", credential.password, 0.98, "site credential password");
  }

  if (credential.username && hasPasswordOnPage && /\b(email|e-mail|username|user name)\b/.test(fieldText)) {
    return answer("workday_credential.username", credential.username, 0.95, "site credential username");
  }

  for (const parsed of parseDefaultAnswers(profile?.default_answers)) {
    if (parsed.label && fieldText.includes(parsed.label)) {
      return answer(`default_answers.${parsed.label}`, parsed.value, 0.9, "default answer");
    }
  }

  let best = null;
  for (const definition of FIELD_DEFINITIONS) {
    const value = String(profile?.[definition.key] || "").trim();
    if (!value) {
      continue;
    }
    const matchedLabel = definition.labels.find((label) => fieldText.includes(label));
    if (!matchedLabel) {
      continue;
    }
    const confidence = confidenceForLabel(matchedLabel, fieldText, field);
    if (!best || confidence > best.confidence) {
      best = answer(definition.key, value, confidence, `matched "${matchedLabel}"`);
    }
  }

  return best && best.confidence >= 0.72 ? best : null;
}

function confidenceForLabel(label, fieldText, field) {
  let confidence = 0.76;
  if (normalizeText(field.label).includes(label)) {
    confidence += 0.12;
  }
  if (normalizeText(field.ariaLabel).includes(label)) {
    confidence += 0.1;
  }
  if (normalizeText(field.name).includes(label.replace(/\s+/g, ""))) {
    confidence += 0.08;
  }
  if (field.required) {
    confidence += 0.02;
  }
  return Math.min(confidence, 0.98);
}

function answer(key, value, confidence, reason) {
  return {
    key,
    value,
    confidence,
    reason,
  };
}
