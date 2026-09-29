"""
A throwaway certificate authority and a local TLS server, for testing how the
server and the controller check a broker's certificate without the internet.

:func:`make_ca` builds a root and a server certificate for ``localhost``;
:func:`tls_server` accepts TLS connections on a free port in a thread.
"""
import datetime
import socket
import ssl
import threading
from contextlib import contextmanager
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def make_ca(folder: Path, name: str = "Test Root", host: str = "localhost") -> dict:
    """
    Create a root certificate and a server certificate it signed.

    Args:
        folder (Path): Where to write ``<name>.pem``, ``server.pem`` and ``server.key``.
        name (str): The root's common name.
        host (str): Name on the server certificate.

    Returns:
        dict: ``root_pem`` (str), ``cert_file`` and ``key_file`` (Path).
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    root_key = ec.generate_private_key(ec.SECP256R1())
    root = (x509.CertificateBuilder().subject_name(_name(name)).issuer_name(_name(name))
            .public_key(root_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), critical=False)
            .sign(root_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (x509.CertificateBuilder().subject_name(_name(host)).issuer_name(root.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
                           critical=False)
            .sign(root_key, hashes.SHA256()))
    folder.mkdir(parents=True, exist_ok=True)
    root_pem = root.public_bytes(serialization.Encoding.PEM).decode("ascii")
    cert_file, key_file = folder / "server.pem", folder / "server.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return {"root_pem": root_pem, "cert_file": cert_file, "key_file": key_file}


def cert_module(pem: str) -> str:
    """The text of a controller ``certs/<name>.py`` file holding one root."""
    return f'"""Test root."""\n\nPEM = """\n{pem.strip()}\n"""\n'


@contextmanager
def tls_server(cert_file: Path, key_file: Path, reply: bytes = b""):
    """
    Accept TLS connections on ``localhost`` until the block ends.

    Each connection gets ``reply`` (e.g. an MQTT CONNACK) after its first read.

    Yields:
        int: The port.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(0.2)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                raw, _ = listener.accept()
            except OSError:
                continue
            try:
                with context.wrap_socket(raw, server_side=True) as conn:
                    conn.settimeout(2)
                    if reply:
                        conn.recv(1024)
                        conn.sendall(reply)
            except (OSError, ssl.SSLError):
                pass  # a client that refused our certificate

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1]
    finally:
        stop.set()
        thread.join(2)
        listener.close()
