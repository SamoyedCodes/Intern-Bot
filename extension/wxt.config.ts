import { defineConfig } from "wxt";

export default defineConfig({
  manifest: {
    name: "Intern-Bot Autofill",
    description: "Human-reviewed Workday autofill powered by the local Intern-Bot profile.",
    permissions: ["activeTab", "storage"],
    host_permissions: [
      "*://*.myworkdayjobs.com/*",
      "*://*.myworkday.com/*"
    ],
    web_accessible_resources: [
      {
        resources: ["page-bridge.js"],
        matches: [
          "*://*.myworkdayjobs.com/*",
          "*://*.myworkday.com/*"
        ]
      }
    ]
  }
});
