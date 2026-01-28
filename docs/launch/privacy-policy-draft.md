# NTRL — Privacy Policy

**[DRAFT — REQUIRES ATTORNEY REVIEW BEFORE PUBLICATION]**

**[DRAFT — THIS DOCUMENT HAS NOT BEEN REVIEWED BY LEGAL COUNSEL. DO NOT PUBLISH OR LINK FROM ANY LIVE PRODUCT UNTIL AN ATTORNEY HAS REVIEWED AND APPROVED THE FINAL VERSION.]**

> **Last Updated:** 2026-01-28
> **Version:** 0.1 (Draft)
> **Effective Date:** [TBD]

---

## Introduction

This Privacy Policy describes how [TBD — Legal Entity Name] ("NTRL," "we," "us," or "our") handles information in connection with the NTRL mobile application (the "App") and related services. NTRL is a news reading application that removes manipulative language from publicly available news articles. We are committed to transparency about our data practices, which are minimal by design.

---

## 1. Information We Collect

### 1.1 Information Stored Locally on Your Device

The App stores the following preferences and data locally on your device using on-device storage (AsyncStorage and Expo SecureStore). This data is **never transmitted to our servers** and remains entirely on your device:

- **Topic Preferences:** Which of the 10 available news categories (World, U.S., Local, Business, Technology, Science, Health, Environment, Sports, Culture) you have enabled or disabled.
- **Text Size Preference:** Your selected text display size within the App.
- **Appearance Preference:** Your light or dark mode selection.
- **Reading History:** A local record of articles you have opened, used solely to track read/unread status within the App.

### 1.2 Information We Do NOT Collect

We want to be explicit about what NTRL does **not** collect, store, or process:

- **No personal identifiers.** We do not collect your name, email address, phone number, or any other personal identifying information.
- **No user accounts.** The App does not require or support account creation, login, or authentication.
- **No location data.** The App does not request or access your device's location services.
- **No device identifiers.** We do not collect device IDs, advertising identifiers (IDFA/GAID), or hardware identifiers.
- **No contacts, photos, camera, or microphone access.** The App does not request access to any of these device features.
- **No analytics or telemetry.** We do not use analytics SDKs, crash reporting services, or telemetry tools that collect usage data.
- **No advertising data.** The App contains no advertisements and no advertising tracking.
- **No user-generated content.** The App does not support comments, posts, reviews, sharing, or any form of user-contributed content.
- **No social features.** The App does not include friend lists, messaging, sharing, or social integrations.

### 1.3 Network Requests

When you use the App, it makes network requests to the NTRL backend API (hosted on Railway) to retrieve news articles and neutralized content. These requests:

- Do **not** include personal identifiers.
- Do **not** include device identifiers.
- Do **not** include authentication tokens (no user accounts exist).
- Contain only the technical information necessary to fulfill the content request (e.g., category, article identifier).

Standard server logs may temporarily record IP addresses as part of normal infrastructure operation. These logs are not used for user identification, tracking, or analytics, and are subject to standard log rotation and deletion.

---

## 2. How We Use Information

### 2.1 Local Preferences

The preferences stored on your device are used solely to:

- Display your selected news categories in your feed.
- Render articles at your chosen text size.
- Apply your chosen appearance (light or dark mode).
- Indicate which articles you have previously read.

These preferences are not transmitted, analyzed, or used for any other purpose.

### 2.2 Article Content

The App retrieves and displays news articles that have been processed by our neutralization engine. This processing:

- Operates on article text sourced from public RSS feeds.
- Uses AI to identify and remove manipulative language (clickbait, emotional triggers, hype, agenda framing).
- Does not involve any user data. Only the text of publicly available articles is processed.

---

## 3. Data Storage

### 3.1 On-Device Storage

All user preferences and reading history are stored locally on your device. If you uninstall the App, this data is deleted. We have no access to this data and cannot recover it.

### 3.2 Backend Storage

Our backend systems store:

- **Article data:** Original and neutralized versions of news articles sourced from public RSS feeds.
- **Article bodies:** Stored in Amazon Web Services (AWS) S3.
- **Processing logs:** Records of the neutralization pipeline for quality assurance purposes.

None of these backend systems store user data, because we do not collect user data.

---

## 4. Third-Party Services

NTRL uses the following third-party services in the operation of the App:

| Service | Purpose | User Data Shared |
|---------|---------|-----------------|
| **OpenAI** | AI-powered article neutralization | None. Only article text from public sources is sent for processing. No user data is transmitted. |
| **Amazon Web Services (AWS) S3** | Storage of article content | None. Only article text is stored. |
| **Railway** | Backend API hosting | None. Standard infrastructure logs only (see Section 1.3). |

We do not share, sell, or provide user data to any third party, because we do not collect user data.

---

## 5. Children's Privacy

NTRL does not knowingly collect personal information from anyone, including children under the age of 13 (or the applicable age in your jurisdiction). The App does not collect personal information from any user, regardless of age.

The App displays news content that is derived from established news organizations. This content may include references to current events, including topics such as politics, conflict, and public health. Parents and guardians should evaluate whether the content is appropriate for their children.

---

## 6. Data Security

Because NTRL does not collect personal data, the security risks associated with personal data breaches are not applicable. Nonetheless, we apply standard security practices to our infrastructure:

- All network communication uses HTTPS/TLS encryption.
- Backend systems follow standard security configurations.
- Access to infrastructure is restricted to authorized personnel.

---

## 7. Your Rights and Choices

Because we do not collect personal data, traditional data rights (access, correction, deletion, portability) do not apply in the conventional sense. However:

- You may **clear local preferences** at any time by uninstalling the App or clearing the App's data through your device settings.
- You may **stop using the App** at any time without consequence, as no account or data exists to manage.

If data protection laws in your jurisdiction grant you rights that you believe apply to your use of NTRL, please contact us at the address below and we will respond in accordance with applicable law.

---

## 8. International Users

The NTRL backend is hosted in the United States via Railway and AWS. Because we do not collect personal data, cross-border data transfer regulations pertaining to personal data do not apply. The article content processed and stored on our servers is derived from publicly available news sources.

---

## 9. Changes to This Privacy Policy

We may update this Privacy Policy from time to time. When we do, we will:

- Update the "Last Updated" date at the top of this document.
- Make the updated policy available within the App and at our privacy policy URL.
- For material changes, provide notice within the App.

Your continued use of the App after changes are posted constitutes acceptance of the revised Privacy Policy.

---

## 10. Contact Us

If you have questions about this Privacy Policy, please contact us at:

**[TBD — Legal Entity Name]**
[TBD — Mailing Address]
[TBD — Contact Email]

---

**[DRAFT — REQUIRES ATTORNEY REVIEW BEFORE PUBLICATION]**
