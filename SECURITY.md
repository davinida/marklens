# Security policy

## Supported code

Security fixes target the current `develop` branch and the most recent tagged release. This
research project does not promise long-term support for older snapshots.

## Reporting

Do not open a public issue containing credentials, unpublished trademark searches, raw KIPRIS
responses, personal data, or a working exploit. Report the issue privately to the repository
maintainers or through GitHub private vulnerability reporting when it is enabled.

Include the affected commit, endpoint, reproduction steps with synthetic data, impact, and any
logs after removing secrets and search terms. Do not test against KIPRIS or a public MarkLens
instance without explicit authorization.

## Secrets

The following values must remain server-side and must never be committed or placed in
`NEXT_PUBLIC_*` variables:

- `KIPRIS_ACCESS_KEY`
- `MARKLENS_API_KEY`
- `MARKLENS_BACKEND_API_KEY` (the BFF-side name for the same backend secret)
- `MARKLENS_TURNSTILE_SECRET_KEY`
- `DATABASE_URL` and database passwords

If exposure is suspected, rotate the credential first, preserve relevant access logs, and then
investigate. The operational response and deployment boundary are documented in
[`docs/MarkLens_공개배포_보안가이드.md`](docs/MarkLens_공개배포_보안가이드.md).

## Non-security limitations

Model disagreement, incomplete KIPRIS coverage, and a visually unexpected candidate are quality
issues unless they can be used to cross an authorization, confidentiality, integrity, or
availability boundary. MarkLens output is not a legal conclusion.
