# Dropbox recording archives (sp-ody-dropbox)

Experimental implementation based on sp-ody `609bc7778`. Backups are **off by
default**. No Dropbox app, account connection, or live upload was created during
development. The stable `sp-ody` branch is unchanged.

## Setup on the comma four

1. The maintainer registers one scoped **App Folder** application in the
   [Dropbox App Console](https://www.dropbox.com/developers/apps), enabling
   `files.content.write` and `files.metadata.read`. The first version leaves the
   public app key configurable. Never enter or commit the app secret.
2. While parked, open Settings → Software → Dropbox backup. Enter the public
   app key and select Connect Dropbox.
3. Scan the QR with a phone, approve in the normal Dropbox browser page, and enter
   the one-time code on the comma. The setup-steps card explains the flow.
4. Enable Dropbox backup. Initial defaults: parked only, unmetered Wi-Fi only,
   full/quick logs and both road-camera files. Preview and recorded cabin video
   are separate opt-ins. Cabin backup does not enable cabin recording.
5. These preferences and read-only status are also published to Sunnylink under
   Device → Dropbox Backup. No Sunnylink website changes are included. Actual
   rendering on the hosted Sunnylink client still needs confirmation.

No callback service, client secret, SSH setup, firmware change, or additional
OS installation is needed. An optional CLI is available for development:
`python -m openpilot.sunnypilot.archive.auth link --app-key PUBLIC_KEY`.

## Architecture

- `core.py`: independent provider protocol, completed-file discovery, policy,
  Dropbox content hashing, and a durable SQLite journal.
- `auth.py`: PKCE authorization requesting offline access, credential files,
  and remote revocation/local cleanup. Access tokens are held in memory.
- `dropbox.py`: 8 MiB upload sessions with durable offsets, token refresh,
  acknowledgement-loss recovery, retries via the worker, and size/hash/path
  verification before confirming a backup.
- `archived.py`: process-manager worker, started only when ArchiveEnabled is true and parked, unless onroad uploads are explicitly enabled.
  Rechecks network freshness, preferences, source state, and account identity
  between chunks. Credentials are not parameters and never enter Sunnylink sync.

On-device private state lives in `/data/odypilot-archive` (directory 0700,
credentials and database 0600); on PC it uses the isolated comma home. Normal
branch updates preserve state. A data reset can remove it and require linking
again. Queues are scoped by Dropbox account and app key, so linking a different
account cannot reuse the first account's upload receipts/sessions.

Within the Dropbox application folder, files are stored as:

```
/<DongleId>/<route>--<segment>/rlog.zst
/<DongleId>/<route>--<segment>/fcamera.hevc
/<DongleId>/<route>--<segment>/ecamera.hevc
```

Only regular, unlocked recordings from the internal log root are eligible.
A new connection backfills eligible recordings still present locally. Remote
paths are deterministic and use overwrite to recover an ambiguous commit without
creating duplicates. Successful receipt records prevent routine re-uploads.
Neither local source files nor comma/Sunnylink upload xattrs are modified.
Remote deletion is never performed. This is a one-way archive, not a sync mirror;
manually deleted Dropbox copies are not automatically checked again once marked done.

## Limits and validation

- Local cleanup remains unchanged and may remove recordings before backup. The
  journal reports unavailable queued files; it does not pin logs or block recording.
- External-storage recordings, raw uncompressed rlog, arbitrary user files,
  automatic MP4 exports, and integration into comma Connect's player are not included.
- The worker does not hold the device awake. Normal shutdown interrupts it; saved
  checkpoints resume on the next allowed connection. Disabled backups run no worker.
- Network loss, drive starts, policy changes, file changes, auth failure, rate
  limits and remote verification failures must not mark a recording backed up.
- No real Dropbox app/account is configured yet. Unit tests simulate only the HTTP
  boundary and use actual files, SQLite, PKCE, hashes and requests.Response objects.
  Live OAuth/upload, on-device operation and hosted Sunnylink UI remain unverified.

References: [Dropbox OAuth](https://docs.dropboxapi.com/dropbox-api/docs/get-started/authorization),
[upload sessions](https://docs.dropboxapi.com/dropbox-api/api-reference/user-endpoints/files/upload-session-start).

## Local validation

- 57 tests passed: queue restart/account separation, file selection and deletion,
  PKCE/private storage, token refresh, interrupted append/finish recovery,
  source modification, pause/HTTP/hash failures, existing Sunnylink and profile tests.
- Sunnylink schema: 10 validation checks passed; parameter/import scans passed.
- Native parameter library rebuilt for the new registered settings.
- Initial settings and linking layouts rendered offscreen on macOS. Later help/status
  refinements passed import checks; a repeat render could not initialize the Mac
  display. Full final on-device UI and real-account integration are still unverified.

Next validation requires the maintainer's public Dropbox App Folder app key and
interactive account approval, followed by a parked-device test of a small log,
interrupted/resumed video, and configuration through hosted Sunnylink.
