# Innovatiview SOP Portal

<p align="center">
  <img src="images/1.png" alt="SOP Portal Dashboard" width="800"/>
</p>

<p align="center">
  <img src="images/2.png" alt="AI Chat Interface" width="800"/>
</p>

An AI-powered, RAG-based Standard Operating Procedure (SOP) management system built for enterprises. Developed for Innovatiview and licensed to multiple enterprise clients, each with a customized document hierarchy.

---

## Overview

The Innovatiview SOP Portal centralises SOP documents in a searchable, role-restricted web application. Employees can query SOPs in natural language through an AI chat interface powered by a local Retrieval-Augmented Generation (RAG) pipeline. Administrators manage documents, users, and permissions through a dedicated dashboard.

The system is architected to support multiple enterprise configurations — the document hierarchy (e.g., Department/Sub-department/Document or Client/Project/Document) is tenant-configurable at the deployment level.

---

## Tech Stack

| Category       | Stack                                      |
|----------------|--------------------------------------------|
| Backend        | Python, Flask, psycopg2                    |
| Database       | PostgreSQL                                 |
| File Storage   | AWS S3 (via boto3)                         |
| PDF Parsing    | XXX                       |
| Email          | Flask-Mail (SMTP/SSL)                      |
| Vector DB      | XXX       |
| Embeddings     | XXX            |
| Primary LLM    | XXX         |
| Frontend       | Jinja2 + Vanilla CSS + Vanilla JS          |
| PWA            | Service Worker + manifest.json             |

---

## Core AI Concept — RAG Pipeline

1. SOP PDFs are parsed, chunked, and embedded via Ollama into ChromaDB
2. When a user submits a question, semantic search retrieves the top-k relevant chunks
3. The LLM generates an answer strictly grounded in the retrieved SOP context — no hallucination outside the document corpus

---

## Role-Based Access Control (RBAC)

Three roles are enforced across the system:

- **Employee** — OTP-based email login, read-only SOP access, AI chat
- **Admin** — Password login, manages documents, categories, and users within their scope
- **Superadmin** — Full control over users, domains, permissions, and system configuration

---

## Database Schema

10 relational tables covering: users, roles, departments/categories, documents, document chunks, vector metadata, OTP tokens, audit logs, permissions, and tenant configuration.

---

## Architecture

---

## Security

- OTP email authentication for employees (no stored passwords)
- Bcrypt password hashing for admin accounts
- Role and domain-scoped document access
- HTTPS-enforced in production
- AWS S3 pre-signed URLs for secure document delivery

---

## PWA Support

The application is installable as a Progressive Web App on desktop and mobile via a Service Worker and `manifest.json`, enabling offline-capable document browsing.

---

## Enterprise Deployments

The portal has been deployed or is in procurement for multiple enterprises, each with a custom document hierarchy:

---


## License

Proprietary — TRPW Strategic Partners. All rights reserved.
