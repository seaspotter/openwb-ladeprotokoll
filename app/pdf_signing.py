"""Self-signed PAdES signing of generated report PDFs.

Pure module -- no DB, no HTTP. A digital signature here proves the PDF
bytes are exactly what was generated and haven't been altered since (an
extension of this project's existing "reports are immutable" guarantee,
see db.py's module docstring), not that the data inside is correct --
`cost_basis="corrected"` reports still show user-entered price overrides,
and the signature doesn't vouch for those being accurate, only that this
is what was actually produced. Self-signed also means the certificate
carries no identity trust chain: a recipient has to explicitly trust it
(by importing `certificate_pem`) to see it as "valid" rather than merely
"intact" in a PDF viewer -- there is no free path to a signature a viewer
trusts automatically without that step (see the conversation that led to
this module for the provider landscape). This is **not** the same thing
as `report_settings.show_signature_line`, which is an unrelated, purely
cosmetic blank line in the PDF footer for a handwritten signature.

Uses pyhanko (PAdES/CMS signing) + cryptography (self-signed X.509
cert/key generation) -- both already vendored as pinned dependencies.
"""
from __future__ import annotations

import datetime
import io

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CERT_VALIDITY_DAYS = 3650  # 10 years -- this is a self-signed identity
# cert for one install, not something that needs frequent rotation; a
# user can regenerate on demand (web.py's /hx/pdf-signing/regenerate)
# if they ever want to invalidate trust in an old one.


class PdfSigningError(Exception):
    pass


def generate_self_signed_cert(common_name: str = "openWB Ladeprotokoll") -> tuple[str, str]:
    """Returns (certificate_pem, private_key_pem), both PEM-encoded `str`
    ready to store directly in report_settings' TEXT columns. RSA-2048/
    SHA-256 -- plenty for a tamper-evidence signature, no need for the
    extra complexity of an EC key here."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=CERT_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            # digital_signature + content_commitment (non-repudiation) is
            # what PAdES/CMS document signing checks for; the rest stay
            # off since this cert is only ever used to sign PDFs, never
            # to encrypt or to sign other certificates.
            x509.KeyUsage(
                digital_signature=True, content_commitment=True, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return cert_pem.decode("ascii"), key_pem.decode("ascii")


def sign_pdf_bytes(pdf_bytes: bytes, certificate_pem: str, private_key_pem: str) -> bytes:
    """Embeds a PAdES signature field into `pdf_bytes` using the given
    self-signed cert/key, returning the signed PDF as new bytes. Raises
    PdfSigningError on any malformed PEM or signing failure -- callers
    decide whether that should block report generation or just skip
    signing (web.py currently does the latter, see _generate_report)."""
    try:
        from pyhanko.keys import pemder
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.sign import PdfSignatureMetadata, sign_pdf
        from pyhanko.sign.signers.pdf_cms import SimpleSigner
        from pyhanko_certvalidator.registry import SimpleCertificateStore

        priv_key_info = pemder.load_private_key_from_pemder_data(
            private_key_pem.encode("ascii"), passphrase=None
        )
        certs = list(pemder.load_certs_from_pemder_data(certificate_pem.encode("ascii")))
        signer = SimpleSigner(
            signing_cert=certs[0],
            signing_key=priv_key_info,
            cert_registry=SimpleCertificateStore(),
        )
        writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes))
        signed_io = sign_pdf(
            writer,
            PdfSignatureMetadata(
                field_name="openWBLadeprotokollSignature",
                reason=(
                    "openWB Ladeprotokoll -- selbstsigniert, bestätigt "
                    "Unveränderung seit Erstellung"
                ),
            ),
            signer=signer,
        )
        return signed_io.getvalue()
    except PdfSigningError:
        raise
    except Exception as exc:  # pyhanko/asn1crypto raise their own exception types
        raise PdfSigningError(f"PDF-Signierung fehlgeschlagen: {exc}") from exc
