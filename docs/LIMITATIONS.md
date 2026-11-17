# Limitations

This repository is a Phase 0 scaffold. It does not yet issue, validate, rotate,
or revoke API keys, enforce quotas, authenticate callers, or expose HTTP routes.

The development credentials in `.env.example` and Docker Compose are for local
development only. Production secrets, database credentials, Redis access
controls, TLS termination, observability, and deployment infrastructure must be
configured for the target environment before deployment.
