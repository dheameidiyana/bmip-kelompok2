#!/usr/bin/env python3
"""Create a local CA and a wildcard certificate for Traefik (W2-C).

Outputs (all gitignored):
  deploy/traefik/certs/bmip-ca.pem
  deploy/traefik/certs/bmip-ca-key.pem
  deploy/traefik/certs/bmip.pem          server certificate + chain
  deploy/traefik/certs/bmip-key.pem      server private key

Trust ``bmip-ca.pem`` on each laptop; see docs/runbooks/traefik-tls.md.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CERT_DIR = ROOT / "deploy" / "traefik" / "certs"
DOMAIN = os.getenv("BMIP_TLS_DOMAIN", "bmip.local")
HOSTS = (
    "api",
    "app",
    "catalog",
    "grafana",
    "prometheus",
    "marquez",
    "minio",
    "prefect",
    "mlflow",
    "docs",
    "alertmanager",
    "n1",
)


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _write(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    ca_path = CERT_DIR / "bmip-ca.pem"
    server_path = CERT_DIR / "bmip.pem"
    if server_path.exists() and ca_path.exists() and not args.force:
        print(f"certificates already exist in {CERT_DIR} (use --force to regenerate)")
        return 0

    now = datetime.now(UTC)
    ca_key = _key()
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(_name("BMIP Local CA"))
        .issuer_name(_name("BMIP Local CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    server_key = _key()
    dns_names = [f"{host}.{DOMAIN}" for host in HOSTS] + ["localhost"]
    ips = [ipaddress.ip_address("127.0.0.1")]
    for extra in os.getenv("BMIP_TLS_IPS", "").split(","):
        extra = extra.strip()
        if extra:
            try:
                ips.append(ipaddress.ip_address(extra))
            except ValueError:
                dns_names.append(extra)
    san = x509.SubjectAlternativeName(
        [x509.DNSName(name) for name in dns_names] + [x509.IPAddress(ip) for ip in ips]
    )
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(_name(f"*.{DOMAIN}"))
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(san, critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    _write(
        CERT_DIR / "bmip-ca.pem",
        ca_cert.public_bytes(serialization.Encoding.PEM),
    )
    _write(
        CERT_DIR / "bmip-ca-key.pem",
        ca_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )
    _write(
        server_path,
        server_cert.public_bytes(serialization.Encoding.PEM)
        + ca_cert.public_bytes(serialization.Encoding.PEM),
    )
    _write(
        CERT_DIR / "bmip-key.pem",
        server_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )
    print(f"wrote certificates for {len(dns_names)} names into {CERT_DIR}")
    print("trust deploy/traefik/certs/bmip-ca.pem as a local root CA")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
