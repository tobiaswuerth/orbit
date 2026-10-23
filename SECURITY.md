# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub:
[Report a vulnerability](https://github.com/tobiaswuerth/orbit/security/advisories/new). Don't open a public issue.
Expect a first reply within a week.

## Supported versions

Security fixes go into the latest release.

## Scope

orbit runs locally and makes no network requests. `orbit serve` binds to `127.0.0.1` by default and has no
authentication, so anyone who can reach its port can read and change the CRM; bound to any other address, it warns
about it. Expose it beyond your machine only behind something that authenticates. Bound to a local address, it
answers only requests that name a local host, so a web page can't reach it under its own domain (DNS rebinding).

orbit writes only inside the vault it serves, and only the notes its tools are about, each atomically. Notes are read
with a strict parser that refuses anchors, tags and nested structures rather than interpreting them. The index lives
in `ORBIT_HOME`, outside the vault, and holds nothing the notes don't.

Notes link local documents as `file://` URLs, which Obsidian opens with a click, but only documents, pictures and
recordings on the same computer: never programs or scripts, which a click would run, and never files on a share,
which would be sent the owner's Windows credentials. What an agent records may come from text written to steer it.
