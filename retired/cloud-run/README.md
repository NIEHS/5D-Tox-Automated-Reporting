# Retired: the Google Cloud Run deployment

Retired by the maintainer on 2026-11-06. The application is no longer deployed
to Cloud Run. These files are kept for the record, not maintained:

- `Dockerfile`: the image. It was already stale before retirement. It predates
  the package layout (ADR-0013): `COPY *.py` copies no code, it starts
  `background_server:app` rather than `web_routes.background_server:app`, it
  needs `cover-bg.jpg`, which no longer exists, and it ships no front end.
- `deploy.sh`: staged the JARs and the knowledge bases, then built and deployed
  one Cloud Run service per user. It called `api.anthropic.com` directly, not
  through the approved gateway.
- `Dockerfile.sync`, `sync.sh`: a session-only redeploy, and the pull of
  sessions back from a running service (`/api/admin/sessions/export`).
- `mount-gcs.sh`: mounted a service's GCS session bucket locally (gcsfuse).
  It was never tracked by git.
- `.gcloudignore`: what Cloud Build uploaded.
- `cloud-deployment-guide.md`: the guide.

What remains in the application from that deployment:
- the `ALLOWED_USERS` `?user=` gate (`web_routes/background_server.py`), which
  `tooling/generate_report_api.sh` also uses;
- the `/api/admin/sessions/export` route;
- `SESSIONS_DIR`, which can be overridden for a mounted bucket (`common/paths.py`).
