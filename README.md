# EduGateBot: Smart Access Control for Academic Content

EduGateBot is an automated, secure Telegram bot designed to streamline the distribution of academic resources (notes, video lectures, and assignments). It features a robust, token-based authorization gating system that enforces a strict 24-hour access window following user ad/shortlink validation, ensuring optimal resource security and monetization workflows.

---

### 🚀 Core Features

- 🔐 **Token-Based Gatekeeping:** Restricts access to premium educational content using custom-generated access tokens.
- ⏳ **24-Hour Expiry Engine:** Enforces dynamic temporal permissions, expiring user access windows exactly 24 hours post-verification.
- 🔗 **Ad-Verification Pipeline:** Integrates link-shortener and ad-gate platform redirects before granting authorization passes.
- 📦 **Containerized Architecture:** Fully dockerized backend for effortless, platform-agnostic cloud micro-deployments.
- 🗄️ **Relational State Tracking:** Uses a secure database schema to map active Telegram user states, generated session tokens, and expiration timestamps.

---

### 💻 Tech Stack

- **Backend Logic:** Python 3.x
- **API Framework:** Flask (Webhook execution and validation routes)
- **Database Engine:** MySQL (Relational user tracking and logging)
- **Deployment & Ops:** Docker, Docker Compose

---

### 🔒 Privacy & Security Configuration

> ⚠️ **CRITICAL PRIVACY NOTE:** To prevent exposing private keys, database passwords, or operational secrets, this project utilizes a strict environment configuration setup. **Never commit raw credentials to your public repository.**

#### 1. Setup Your Local Environment Variables
Create a file named `.env` in the root directory of your project (this file is automatically ignored by Git) and populate it with your specific system configurations:
