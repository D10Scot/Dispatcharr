"""OpenID Connect sign-in (SSO spec docs/superpowers/specs/2026-10-31-sso-oidc-design.md).

PR S1 holds the storage and the admin side: encrypted credentials, certificates, discovery
and JWKS fetching, audit events. The login flow is PR S2.
"""
