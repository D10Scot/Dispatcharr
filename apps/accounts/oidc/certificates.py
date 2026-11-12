"""Client key pair and self-signed certificate for ``private_key_jwt`` (SSO spec 5.2, ruling B4).

Generated in the app and never uploaded: the private key exists in one place, is stored as
Fernet ciphertext, and no API returns it. What an admin carries to the IdP is the public
certificate. Building the client assertion from the active pair is PR S2's.
"""

import datetime
import hashlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from gevent import monkey

CERT_VALID_DAYS = 730
KEY_SIZE = 2048


def generate_pair(slug):
    """Return ``(private_key_pem, certificate_pem)`` as text. RSA 2048, SHA-256, 730 days.

    RSA key generation is CPU-bound and does not yield to gevent: inline, it stalls every
    other request greenlet on the uWSGI worker for its whole duration (measured at a 23 ms
    median and up to 90 ms on a fast host). Under gevent's monkey-patching it therefore runs
    on the hub's native threadpool, where the OpenSSL call releases the GIL and the hub keeps
    scheduling; the calling greenlet waits and any exception re-raises in it unchanged. Every
    process that is not monkey-patched (tests, management commands, Celery, Daphne)
    generates inline, as before.
    """
    if monkey.is_module_patched("socket"):
        import gevent

        return gevent.get_hub().threadpool.apply(_generate_pair, (slug,))
    return _generate_pair(slug)


def _generate_pair(slug):
    key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"mino-oidc-{slug}")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=CERT_VALID_DAYS))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    return key_pem, cert_pem


def load_certificate(cert_pem):
    return x509.load_pem_x509_certificate(cert_pem.encode("ascii"))


def thumbprint_sha256(cert_pem):
    """Lowercase hex SHA-256 of the certificate's DER encoding."""
    der = load_certificate(cert_pem).public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(der).hexdigest()


def not_after(cert_pem):
    return load_certificate(cert_pem).not_valid_after_utc


def describe(cert_pem):
    """``{thumbprint_sha256, not_after}`` for a stored certificate, or None when the slot is empty."""
    if not cert_pem:
        return None
    return {
        "thumbprint_sha256": thumbprint_sha256(cert_pem),
        "not_after": not_after(cert_pem).isoformat(),
    }
