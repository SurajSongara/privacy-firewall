# Security Policy

Privacy Firewall is a tool for **removing** sensitive information, so its own
security and correctness matter more than usual. This document covers how to
report issues and what the tool does and does not guarantee.

## Privacy posture

- **Fully offline.** No network calls, no telemetry, no cloud OCR. Parsing, OCR,
  detection, and redaction all run locally.
- **Localhost only.** The Studio web UI binds to `127.0.0.1`; it is not exposed
  on the network.
- **In-memory secrets.** Passwords for encrypted PDFs are held in memory only and
  never written to disk. Redacted output of an encrypted source is written
  unencrypted so it can be shared.
- **Originals are never modified.** The renderer always writes to a new file.

## What redaction guarantees

- **True removal, not masking.** Matched text is deleted from the PDF content
  stream and the page is regenerated; copy-paste and text extraction find
  nothing. Scanned-page pixels under a redaction are zeroed.
- **Hidden surfaces are stripped.** Document metadata (Title/Author/Subject/
  Keywords) and annotations/form-field values are scanned and removed.
- **Verification.** `--certificate` re-parses the output, re-runs every detector,
  and re-scans metadata/annotations; if any redacted value is still extractable
  the certificate **fails** and the CLI exits non-zero.

## Known limitations (read before relying on it)

- **Free-text names are best-effort.** The engine is deterministic with no NER
  model, so it catches names it can corroborate (an email handle, a UPI slug, a
  labelled field) but may miss a bare name with no anchor. Use Studio's
  drag-select / "remember" to mark those. The certificate will fail loudly if a
  value you marked survives, so you always know.
- **Phone vs. transaction references.** A bare 10-digit UTR/reference can look
  like a phone number; context scoring suppresses most, but precision on
  adversarial inputs is imperfect.
- **Always review before sharing** a redacted document that contains PII the
  detectors are not designed for.

## Reporting a vulnerability or a leak

If you find a case where redacted output still leaks a value, or any other
security issue, please **report it privately** rather than opening a public
issue:

- Use GitHub's **[Report a vulnerability](https://github.com/SurajSongara/privacy-firewall/security/advisories/new)**
  (Security → Advisories) to open a private advisory, **or**
- Open a minimal issue that describes the *class* of problem without attaching
  any real sensitive document.

Please include a **synthetic** reproduction (fabricated values only) — never real
personal data. We aim to acknowledge reports promptly and will credit reporters
who wish to be named.
