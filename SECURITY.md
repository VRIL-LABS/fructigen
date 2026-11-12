# Security policy

## Supported versions

Fructigen is in alpha. Only the latest commit on `main` receives security fixes.

| Version | Supported |
|---|---|
| `main` | yes |
| `0.1.0a0` and earlier | no |

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Email **support@vril.li** with "Fructigen security" in the subject. Include:

- what is affected (module, function, or commit);
- how to reproduce it;
- what an attacker could do with it.

We aim to acknowledge a report within five business days and to agree a disclosure date with you
before any fix is published.

## What counts as a security issue here

Fructigen decides which prompt content is shared between agents and which cached content a request
may reuse. Problems in that area matter most:

- content from one scope (model, system prompt, tools or settings) being treated as reusable in
  another, which `segment.scope_digest` exists to prevent;
- a verifier being allowed to reuse anything other than an exact prefix of the worker's request
  (ruling R40a in the framework repository);
- an attestation check (`attest.check_path`) passing a request that differs from its plan;
- once the planned `store` and `pqc` modules exist: key handling, signature verification, and
  anything that writes plaintext to disk.

Model output and retrieved content are untrusted data. A path where either is executed or treated as
an instruction is a security issue.
