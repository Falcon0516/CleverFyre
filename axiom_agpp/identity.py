"""
AXIOM AgPP — Deterministic Agent Identity

Derives a deterministic Algorand keypair from organizational secrets,
agent role, and a SHA-256 hash of the agent's source code.

Key property: same inputs ALWAYS produce the same Algorand address.
Change one byte of the agent's code → the address changes automatically.
This provides tamper-detection at the identity layer — no wallet files,
no key management, no external dependencies.

Identity derivation (AgPP Layer 1):
    code_hash  = SHA-256(file at code_path)
    ikm        = org_id + ":" + agent_role + ":" + code_hash
    seed       = HMAC-SHA256(org_secret, ikm)       → 32 bytes
    keypair    = Ed25519.from_seed(seed)             → deterministic
    address    = Algorand base32 encoding of pubkey

Usage:
    from axiom_agpp.identity import derive_agent_address
    private_key, address = derive_agent_address(
        org_secret=b"hackathon-secret-2026",
        org_id="acme-corp",
        agent_role="market-researcher",
        code_path="my_agent.py"
    )
"""

import base64
import hashlib
import hmac
import logging
from typing import Tuple

import algosdk.encoding
from nacl.signing import SigningKey

logger = logging.getLogger(__name__)


def derive_agent_address(
    org_secret: bytes,
    org_id: str,
    agent_role: str,
    code_path: str,
) -> Tuple[str, str]:
    """
    Derive a deterministic Algorand keypair from org identity and agent code.

    The same inputs always produce the same (private_key, address) pair.
    Changing even one byte in the file at code_path produces a completely
    different address — this is the tamper-detection mechanism.

    Args:
        org_secret:  Organization master secret (bytes). Used as HMAC key.
                     Example: b"hackathon-secret-2026"
        org_id:      Organization identifier string. Example: "acme-corp"
        agent_role:  Agent role identifier. Example: "market-researcher"
        code_path:   Path to the agent's source code file. Its SHA-256 hash
                     is included in the key derivation — any code change
                     produces a new identity.

    Returns:
        Tuple of (private_key, algorand_address):
            private_key     — Base64-encoded 64-byte Ed25519 signing key
                              (in the format algosdk expects)
            algorand_address — Standard Algorand base32 address (58 chars)

    Example:
        >>> pk, addr = derive_agent_address(b"secret", "org", "role", "agent.py")
        >>> assert len(addr) == 58  # standard Algorand address length
        >>> pk2, addr2 = derive_agent_address(b"secret", "org", "role", "agent.py")
        >>> assert addr == addr2    # deterministic — same inputs, same output
    """

    # ── Step 1: Hash the agent's source code ──────────────────────
    # Read file in binary mode to get consistent hashes across platforms
    try:
        with open(code_path, "rb") as f:
            code_bytes = f.read()
    except FileNotFoundError:
        logger.warning(
            "Code path not found: %s — using path string as fallback hash input",
            code_path,
        )
        code_bytes = code_path.encode()

    code_hash = hashlib.sha256(code_bytes).hexdigest()

    # ── Step 2: Build Input Key Material (IKM) ────────────────────
    # Format: "org_id:agent_role:code_hash"
    # This binds the identity to the org, the role, AND the exact code
    ikm = f"{org_id}:{agent_role}:{code_hash}".encode()

    # ── Step 3: Derive 32-byte seed via HMAC-SHA256 ───────────────
    # HMAC ensures the seed is uniformly distributed and bound to org_secret
    seed = hmac.new(org_secret, ikm, hashlib.sha256).digest()
    # seed is exactly 32 bytes — perfect for Ed25519 key derivation

    # ── Step 4: Derive deterministic Ed25519 keypair ──────────────
    # Ed25519 from a fixed seed always produces the same keypair
    signing_key = SigningKey(seed)
    verify_key = signing_key.verify_key

    # ── Step 5: Encode in algosdk format ──────────────────────────
    # algosdk private key = base64(signing_key_bytes + verify_key_bytes)
    # This is the 64-byte Ed25519 expanded key format
    private_key_bytes = bytes(signing_key) + bytes(verify_key)
    private_key_b64 = base64.b64encode(private_key_bytes).decode()

    # Algorand address = base32 encoding of the 32-byte public key + checksum
    address = algosdk.encoding.encode_address(bytes(verify_key))

    logger.info(
        "Derived agent identity — org=%s role=%s code_hash=%s...%s addr=%s",
        org_id,
        agent_role,
        code_hash[:8],
        code_hash[-4:],
        address[:8] + "..." + address[-4:],
    )

    return private_key_b64, address


def verify_agent_identity(
    org_secret: bytes,
    org_id: str,
    agent_role: str,
    code_path: str,
    expected_address: str,
) -> bool:
    """
    Verify that an agent's current code produces the expected address.

    Returns False if the code has been tampered with (address mismatch).

    Args:
        org_secret:       Organization master secret.
        org_id:           Organization identifier.
        agent_role:       Agent role identifier.
        code_path:        Path to the agent's source code.
        expected_address: The Algorand address the agent should have.

    Returns:
        True if the derived address matches expected_address, False otherwise.
    """
    _, actual_address = derive_agent_address(org_secret, org_id, agent_role, code_path)
    match = actual_address == expected_address

    if not match:
        logger.warning(
            "IDENTITY MISMATCH — expected %s, got %s. Agent code may be tampered!",
            expected_address[:12] + "...",
            actual_address[:12] + "...",
        )

    return match


def get_code_hash(code_path: str) -> str:
    """
    Compute SHA-256 hash of a file. Useful for debugging identity issues.

    Args:
        code_path: Path to the file.

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    with open(code_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ─────────────────────────────────────────────────────────────────
#  MAIN — Test Derivation
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("═══════════════════════════════════════════════════")
    print("  AXIOM AgPP — Identity Derivation Test")
    print("═══════════════════════════════════════════════════\n")

    # Test with this file itself as the code_path
    test_secret = b"hackathon-secret-2026"
    test_org = "acme-corp"
    test_role = "market-researcher"
    test_code = __file__

    pk1, addr1 = derive_agent_address(test_secret, test_org, test_role, test_code)
    pk2, addr2 = derive_agent_address(test_secret, test_org, test_role, test_code)

    print(f"  Org:          {test_org}")
    print(f"  Role:         {test_role}")
    print(f"  Code path:    {test_code}")
    print(f"  Code hash:    {get_code_hash(test_code)[:16]}...")
    print(f"  Address:      {addr1}")
    print(f"  Private key:  {pk1[:20]}...{pk1[-8:]}")
    print()

    # Determinism check
    assert addr1 == addr2, "FAIL: Same inputs produced different addresses!"
    print("  ✓ Determinism check passed (same inputs → same address)")

    # Different role → different address
    _, addr3 = derive_agent_address(test_secret, test_org, "different-role", test_code)
    assert addr1 != addr3, "FAIL: Different roles produced same address!"
    print("  ✓ Role isolation check passed (different role → different address)")

    # Different org → different address
    _, addr4 = derive_agent_address(test_secret, "other-org", test_role, test_code)
    assert addr1 != addr4, "FAIL: Different orgs produced same address!"
    print("  ✓ Org isolation check passed (different org → different address)")

    # Different secret → different address
    _, addr5 = derive_agent_address(b"different-secret", test_org, test_role, test_code)
    assert addr1 != addr5, "FAIL: Different secrets produced same address!"
    print("  ✓ Secret isolation check passed (different secret → different address)")

    # Identity verification
    assert verify_agent_identity(test_secret, test_org, test_role, test_code, addr1)
    print("  ✓ Identity verification passed")

    print("\n═══════════════════════════════════════════════════")
    print("  All identity tests passed!")
    print("═══════════════════════════════════════════════════")
