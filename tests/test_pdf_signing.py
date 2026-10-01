from cryptography import x509
from cryptography.hazmat.primitives import serialization
from pyhanko.keys import pemder
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator.context import ValidationContext
from weasyprint import HTML
import io

from app.pdf_signing import generate_self_signed_cert, sign_pdf_bytes, PdfSigningError


def test_generate_self_signed_cert_shape():
    cert_pem, key_pem = generate_self_signed_cert("Test Org")
    assert cert_pem.startswith("-----BEGIN CERTIFICATE-----")
    assert key_pem.startswith("-----BEGIN PRIVATE KEY-----")

    cert = x509.load_pem_x509_certificate(cert_pem.encode("ascii"))
    assert cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value == "Test Org"
    # Self-signed: issuer and subject are identical.
    assert cert.issuer == cert.subject

    key = serialization.load_pem_private_key(key_pem.encode("ascii"), password=None)
    assert key.key_size == 2048


def test_generate_self_signed_cert_default_common_name():
    cert_pem, _ = generate_self_signed_cert()
    cert = x509.load_pem_x509_certificate(cert_pem.encode("ascii"))
    cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
    assert cn == "openWB Ladeprotokoll"


def _sample_pdf_bytes() -> bytes:
    return HTML(string="<html><body><h1>Test</h1></body></html>").write_pdf()


def test_sign_pdf_bytes_produces_valid_trusted_signature():
    cert_pem, key_pem = generate_self_signed_cert()
    signed = sign_pdf_bytes(_sample_pdf_bytes(), cert_pem, key_pem)

    assert signed.startswith(b"%PDF")
    assert len(signed) > len(_sample_pdf_bytes())

    reader = PdfFileReader(io.BytesIO(signed))
    assert len(reader.embedded_signatures) == 1
    sig = reader.embedded_signatures[0]

    trust_root = list(pemder.load_certs_from_pemder_data(cert_pem.encode("ascii")))[0]
    vc = ValidationContext(trust_roots=[trust_root], allow_fetching=False)
    status = validate_pdf_signature(sig, signer_validation_context=vc)

    assert status.intact
    assert status.valid
    assert status.trusted


def test_sign_pdf_bytes_wrong_cert_not_trusted():
    """A signature validated against a DIFFERENT self-signed cert than the
    one that actually signed it should not come back trusted -- confirms
    this isn't a no-op that always reports "trusted" regardless of input."""
    cert_pem, key_pem = generate_self_signed_cert()
    other_cert_pem, _ = generate_self_signed_cert("Someone Else")
    signed = sign_pdf_bytes(_sample_pdf_bytes(), cert_pem, key_pem)

    reader = PdfFileReader(io.BytesIO(signed))
    sig = reader.embedded_signatures[0]
    other_root = list(pemder.load_certs_from_pemder_data(other_cert_pem.encode("ascii")))[0]
    vc = ValidationContext(trust_roots=[other_root], allow_fetching=False)
    status = validate_pdf_signature(sig, signer_validation_context=vc)

    assert status.intact  # still cryptographically intact...
    assert not status.trusted  # ...but not trusted against the wrong root


def test_sign_pdf_bytes_malformed_key_raises():
    cert_pem, _ = generate_self_signed_cert()
    try:
        sign_pdf_bytes(_sample_pdf_bytes(), cert_pem, "not a real key")
    except PdfSigningError:
        pass
    else:
        raise AssertionError("expected PdfSigningError")
