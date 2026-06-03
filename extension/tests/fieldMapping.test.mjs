import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  getCredentialForHost,
  mapFieldToAnswer,
  parseDefaultAnswers,
} from "../src/fill/fieldMapping.js";

describe("field mapping", () => {
  it("maps obvious profile fields by label", () => {
    const answer = mapFieldToAnswer(
      { label: "First Name", type: "text", value: "" },
      { first_name: "Ada" },
      "example.wd3.myworkdayjobs.com",
    );

    assert.equal(answer.key, "first_name");
    assert.equal(answer.value, "Ada");
  });

  it("uses Workday credentials on sign-in pages", () => {
    const answer = mapFieldToAnswer(
      {
        label: "Email Address",
        type: "email",
        value: "",
        pageHints: { hasPasswordField: true },
      },
      {
        email: "personal@example.com",
        workday_credentials: {
          "example.wd3.myworkdayjobs.com": {
            username: "example_intern@applications.example.com",
            password: "Secure123!",
          },
        },
      },
      "example.wd3.myworkdayjobs.com",
    );

    assert.equal(answer.key, "workday_credential.username");
    assert.equal(answer.value, "example_intern@applications.example.com");
  });

  it("parses default answer lines", () => {
    assert.deepEqual(parseDefaultAnswers("Require sponsorship: No"), [
      { label: "require sponsorship", value: "No" },
    ]);
  });

  it("normalizes credential hosts", () => {
    const credential = getCredentialForHost(
      {
        workday_credentials: {
          "company.wd1.myworkdayjobs.com": { username: "u", password: "p" },
        },
      },
      "company.wd1.myworkdayjobs.com",
    );

    assert.equal(credential.username, "u");
  });
});
