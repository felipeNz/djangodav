# Security audit — 11 October 2026

Scope: the Python library, filesystem and database resource backends, DAV
handlers, authentication adapters, templates, dependency declarations and CI.
This repository is a reusable library, without production settings or a deployed
service. This review cannot certify an application's deployment or custom backends.

## Findings fixed

| Severity | Finding | Change |
| --- | --- | --- |
| High | Filesystem paths could escape the configured root through `..`, Windows path syntax, or links. | Validate every filesystem access, enforce resolved-root containment, reject symlinks/junctions and Windows reserved names. |
| High | COPY/MOVE could overwrite destinations without destination authorization. Recursive operations could change protected children. | Preflight destination parent, destination and descendant permissions, including each copied target; check recursive DELETE permissions before mutation. |
| High | Collection listings and PROPFIND exposed unreadable children's metadata and dead properties. | Filter directory listings and prune unreadable PROPFIND branches. |
| High | CSRF-exempt DAV dispatch permitted unsafe operations using ambient session authentication. | Enforce Django CSRF checks for authenticated session requests. The REST adapter marks successful non-session authentication explicitly; arbitrary Authorization headers cannot bypass checks. |
| High | Uploaded HTML/SVG could execute in the application's origin when downloaded. | Serve objects as attachments with `nosniff`, including accelerated downloads. |
| Medium | COPY/MOVE destination URLs weren't constrained to the DAV mount; overlapping paths could destroy data or recursively copy into themselves. | Check origin and mount boundaries, reject query/fragment destinations and overlapping resource paths before deletion. |
| Medium | Malformed XML and content headers raised server errors; XML bodies and recursive property listings lacked limits. | Return 400 for invalid XML/entities/DTD and invalid Content-Length; cap XML bodies at 1 MiB, disable infinite PROPFIND by default and cap traversed resources at 10,000. |
| Medium | Content-Disposition filenames could inject parameters or contain control characters. | Escape quoted filenames, remove control characters and percent-encode extended filenames. |
| Low | Accelerated download handling opened files repeatedly and handled absolute Windows paths incorrectly. | Close the source handle, compute a relative path and reject redirects outside the root. |
| Low | CI omitted the mandatory XML security dependency; dependency declarations allowed earlier releases than those audited. | Install requirements in CI and raise minimum versions to the tested releases. |

## Compatibility changes

- Session-authenticated writes must supply a valid Django CSRF token. Native DAV
  clients should use explicit authentication, such as the REST BasicAuthentication
  adapter over HTTPS. Custom non-session adapters need review; Tastypie requests
  with authenticated users conservatively receive CSRF checks.
- Files download as attachments, including HTML and SVG.
- Linked filesystem resources, traversal components, Windows special names and
  names ending in dots or spaces are rejected.
- Infinite PROPFIND requires `DJANGODAV_ALLOW_INFINITE_PROPFIND=True`.
  `DJANGODAV_MAX_XML_BYTES` and `DJANGODAV_MAX_PROPFIND_RESOURCES` configure limits.
  Set positive, finite values and consider deployment capacity before increasing them.
- Deleting the DAV root and overlapping COPY/MOVE operations are forbidden.

## Validation

- Full Django test suite: 70 tests, passing; one actual symlink test skipped
  because Windows symlink creation is unavailable. Regression tests cover
  traversal, destination permissions, overlapping paths, recursive deletion,
  unreadable branches, XML errors/limits, session CSRF and filename escaping.
- Existing tests were updated for Python 3 bytes, streaming responses, realistic
  request objects, filesystem portability and the corrected security behavior.
- `pip-audit` of the isolated installed environment: no known vulnerabilities.
  Tested runtime: Python 3.13, Django 6.1.2, DRF 3.18.3, defusedxml 0.7.1.
  Dependency ranges are not a reproducible production lockfile; audit the exact
  production environment again when dependencies change.
- Current-file credential-pattern scan found no matching private keys, AWS access
  keys, GitHub tokens or literal SECRET_KEY/password assignments. This was not a
  forensic scan of Git history or a guarantee that no secrets exist.

## Deployment and design limits

- Configure authentication and resource-specific ACLs in the host application.
  The base view is readable without authentication by default. Never expose
  private data using that default, or grant public write permissions accidentally.
- Use HTTPS, secure cookies, correct ALLOWED_HOSTS, DEBUG=False and appropriate
  proxy settings. Run Django's `check --deploy` with actual production settings.
  Restrict accelerated-download routes to internal server access.
- Set proxy upload-size limits, request timeouts, per-user quotas and rate limits.
  PUT streams to disk; the library cannot choose the application's storage quota.
- Keep the configured filesystem root exclusively managed by the service.
  Path validation is not an atomic defense against a hostile local process changing
  directories between validation and access. Local untrusted filesystem writers
  need OS isolation or a backend using descriptor-relative atomic operations.
- Filesystem COPY/MOVE and writes are not transactional. Concurrent requests or
  I/O failures can leave partial changes. Permission preflight is also not atomic
  with concurrent ACL changes; serialize operations where necessary.
- DummyLock is a no-op, and this library does not enforce DAV lock tokens before
  mutations. Do not rely on advertised DAV locking for concurrency or access
  control; use a backend that implements and enforces locking if required.
- Custom resource/ACL/authentication subclasses and a live server require their
  own review and integration testing. Database access here uses ORM queries;
  custom model scopes must isolate tenants.

Reference for session protection:
[Django CSRF documentation](https://docs.djangoproject.com/en/6.0/ref/csrf/).
