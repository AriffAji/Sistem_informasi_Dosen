# Isi BARU (Versi 3) untuk generate_keys.py
# Kita akan menggunakan library cryptography secara langsung untuk membuat kunci.

import base64
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

print("Sedang membuat VAPID keys menggunakan cryptography langsung...")

try:
    # 1. Buat private key menggunakan kurva P-256 (SECP256R1)
    private_key = ec.generate_private_key(ec.SECP256R1())

    # 2. Dapatkan public key dari private key
    public_key = private_key.public_key()

    # 3. Serialisasi private key (ambil angka mentahnya)
    # Private key VAPID adalah nilai integer mentah 32 byte.
    private_value_bytes = private_key.private_numbers().private_value.to_bytes(32, byteorder='big')
    
    # 4. Serialisasi public key (format uncompressed point)
    # Public key VAPID menggunakan format X962 uncompressed (byte 0x04 diikuti 64 byte data x,y).
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )

    # 5. Encode ke base64 url-safe (format standar VAPID)
    private_key_b64 = base64.urlsafe_b64encode(private_value_bytes).rstrip(b'=').decode('utf-8')
    public_key_b64 = base64.urlsafe_b64encode(public_key_bytes).rstrip(b'=').decode('utf-8')

    print("\n--- BERHASIL MEMBUAT KUNCI ---")
    print(f"Public Key: {public_key_b64}")
    print(f"Private Key: {private_key_b64}")
    print("---------------------------------")

except Exception as e:
    print(f"\n[ERROR] Terjadi kesalahan saat membuat kunci: {e}")