# Security

LeftoverAchievements is a self-hosted application intended for a device you control
and, when LAN access is enabled, a trusted home network. It does not provide user
accounts or internet-facing authentication. Do not expose its server port directly
to the public internet.

## RetroAchievements API key

The application uses the key only for HTTPS requests to the official
`retroachievements.org` API. The API requires the key as the `y` query parameter.
The key is never returned by an application route or rendered back into a form.

Normal setup stores the key in the local SQLite database. On POSIX systems the
database is created with owner-only permissions (`0600`). Packaged application data
lives outside the application bundle, and database, environment, and runtime files
are excluded from release archives. The `.env` mechanism is a development fallback
and `.env` is ignored by Git.

Application error output redacts saved keys, credential-shaped query parameters,
authorization headers, and common secret fields before showing log details in the
Settings UI. Avoid enabling third-party HTTP debug logging, because the upstream API
places its credential in the URL.

## Browser and network boundary

State-changing browser requests identified by Origin or Fetch Metadata must be
same-origin. Cross-site form and fetch requests are rejected, and responses include a
baseline Content Security Policy plus anti-framing, MIME-sniffing, referrer, and
permissions headers. Command-line and native clients may omit browser origin headers.

Hub addresses are explicitly entered by an administrator and are restricted to an
HTTP(S) origin without embedded credentials, path, query, or fragment. A candidate
must answer the application hub-status protocol before it is saved.

Custom alert audio is size-limited, stored under an application-chosen filename, and
checked for the expected MP3, WAV, or Ogg container signature before it is served.

## Reporting a vulnerability

Use the repository's Security tab to submit a private report when that option is
available; otherwise contact the maintainer privately through their GitHub profile.
Include the affected version, reproduction steps, and observed impact. Do not open a
public issue for an unpatched vulnerability or include a real API key in a report.
