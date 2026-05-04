"""
Extracted selectors for Workday ATS automation.
"""

# Button Selectors
CREATE_ACCOUNT = [
    'button:has-text("Create Account")',
    '[data-automation-id="createAccountSubmitButton"]',
    '[data-automation-id="click_filter"]',
]

SIGN_IN_NAVIGATION = [
    '#mainContent button:has-text("Sign In")',
    'button:has-text("Sign In")',
    'a:has-text("Sign In")',
    '[data-automation-id*="signIn" i]',
]

SIGN_IN_SUBMIT = [
    'button:has-text("Sign In")',
    '[role="button"]:has-text("Sign In")',
    'button:has-text("Log In")',
    '[role="button"]:has-text("Log In")',
    'button:has-text("Login")',
    '[role="button"]:has-text("Login")',
    'button[type="submit"]',
    '[data-automation-id*="signIn" i]',
    '[data-automation-id="click_filter"]',
]

APPLY_NOW = [
    '[data-automation-id="applyNowButton"]',
    'button:has-text("Apply")',
    'a:has-text("Apply")',
]

AUTOFILL_RESUME = [
    'button:has-text("Autofill with Resume")',
    'a:has-text("Autofill with Resume")',
    '[data-automation-id="autofillWithResume"]',
    '[data-automation-id="autofillWithResumeButton"]',
]

CONTINUE = [
    '[data-automation-id="bottom-navigation-next-button"]',
    '[data-automation-id="bottomNavigationNextButton"]',
    '[data-automation-id*="next" i]',
    'button:has-text("Save and Continue")',
    'button:has-text("Save & Continue")',
    'button:has-text("Continue")',
    'button:has-text("Next")',
    'a:has-text("Continue")',
    'a:has-text("Next")',
]

# Sign In Inputs
EMAIL_INPUT = [
    'input[type="email"]',
    'input[autocomplete="username"]',
    'input[data-automation-id="email"]',
    'input[data-automation-id*="email" i]',
    'input[data-automation-id*="user" i]',
    'input[name*="email" i]',
    'input[name*="user" i]',
    'input[id*="email" i]',
    'input[id*="user" i]',
]

PASSWORD_INPUT = [
    'input[type="password"]',
    'input[data-automation-id*="password" i]',
    'input[name*="password" i]',
    'input[id*="password" i]',
]

# Page Identification
APP_QUESTIONS_PAGE = [
    'text="Application Questions"',
    '[aria-current="step"]:has-text("Application Questions")',
    '[data-automation-id*="applicationQuestions" i]',
    'h1:has-text("Application Questions")',
    'h2:has-text("Application Questions")',
]

SIGN_IN_PAGE = [
    'input[type="password"]',
    'button:has-text("Sign In")',
    '[role="button"]:has-text("Sign In")',
    'button:has-text("Log In")',
    '[data-automation-id*="signIn" i]',
]

CONSENT_CHECKBOX = [
    'label:has-text("candidate profile") input[type="checkbox"]',
    'label:has-text("explicit consent") input[type="checkbox"]',
    'input[type="checkbox"]'
]

# Profile Groups
PROFILE_FIELDS = [
    ("first_name", [
        'input[name*="firstName" i]',
        'input[id*="firstName" i]',
        'input[data-automation-id*="firstName" i]',
        'input[aria-label*="First Name" i]',
    ]),
    ("last_name", [
        'input[name*="lastName" i]',
        'input[id*="lastName" i]',
        'input[data-automation-id*="lastName" i]',
        'input[aria-label*="Last Name" i]',
    ]),
    ("email", [
        'input[type="email"]',
        'input[name*="email" i]',
        'input[id*="email" i]',
        'input[data-automation-id*="email" i]',
        'input[aria-label*="Email" i]',
    ]),
    ("phone", [
        'input[type="tel"]',
        'input[name*="phone" i]',
        'input[id*="phone" i]',
        'input[data-automation-id*="phone" i]',
        'input[aria-label*="Phone" i]',
    ]),
    ("address", [
        'input[name*="address" i]',
        'input[name*="location" i]',
        'input[id*="address" i]',
        'input[id*="location" i]',
        'input[data-automation-id*="address" i]',
        'input[data-automation-id*="location" i]',
        'input[aria-label*="Location" i]',
    ]),
    ("linkedin_url", [
        'input[name*="linkedin" i]',
        'input[id*="linkedin" i]',
        'input[data-automation-id*="linkedin" i]',
        'input[aria-label*="LinkedIn" i]',
    ]),
    ("github_url", [
        'input[name*="github" i]',
        'input[id*="github" i]',
        'input[data-automation-id*="github" i]',
        'input[aria-label*="GitHub" i]',
    ]),
    ("portfolio_url", [
        'input[name*="portfolio" i]',
        'input[name*="website" i]',
        'input[id*="portfolio" i]',
        'input[id*="website" i]',
        'input[data-automation-id*="portfolio" i]',
        'input[data-automation-id*="website" i]',
    ]),
    ("school", [
        'input[name*="school" i]',
        'input[name*="institution" i]',
        'input[id*="school" i]',
        'input[id*="institution" i]',
        'input[data-automation-id*="school" i]',
    ]),
    ("degree", [
        'input[name*="degree" i]',
        'input[id*="degree" i]',
        'input[data-automation-id*="degree" i]',
    ]),
    ("major", [
        'input[name*="major" i]',
        'input[name*="fieldOfStudy" i]',
        'input[id*="major" i]',
        'input[id*="fieldOfStudy" i]',
        'input[data-automation-id*="major" i]',
    ]),
    ("graduation", [
        'input[name*="graduation" i]',
        'input[name*="gradDate" i]',
        'input[id*="graduation" i]',
        'input[id*="gradDate" i]',
        'input[data-automation-id*="graduation" i]',
    ]),
]

EXPERIENCE_FIELDS = [
    ("employer", [
        'input[name*="employer" i]',
        'input[name*="company" i]',
        'input[id*="employer" i]',
        'input[id*="company" i]',
        'input[data-automation-id*="employer" i]',
        'input[data-automation-id*="company" i]',
    ]),
    ("job_title", [
        'input[name*="jobTitle" i]',
        'input[name*="title" i]',
        'input[id*="jobTitle" i]',
        'input[id*="title" i]',
        'input[data-automation-id*="jobTitle" i]',
    ]),
    ("location", [
        'input[name*="location" i]',
        'input[id*="location" i]',
        'input[data-automation-id*="location" i]',
    ]),
    ("start_date", [
        'input[name*="startDate" i]',
        'input[id*="startDate" i]',
        'input[data-automation-id*="startDate" i]',
    ]),
    ("end_date", [
        'input[name*="endDate" i]',
        'input[id*="endDate" i]',
        'input[data-automation-id*="endDate" i]',
    ]),
    ("description", [
        'textarea[name*="description" i]',
        'textarea[name*="responsib" i]',
        'textarea[id*="description" i]',
        'textarea[id*="responsib" i]',
        'textarea[data-automation-id*="description" i]',
    ]),
]
