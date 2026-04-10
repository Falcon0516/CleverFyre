from algopy import ARC4Contract, BoxMap, Bytes, Txn, Global, op
from algopy.arc4 import abimethod


class IntentRegistry(ARC4Contract):
    """
    IntentRegistry — Layer 2 of AgPP.

    Stores:
      session_roots: session_id (32B) -> merkle_root (32B)
      intent_cids:   tx_id_hash (32B) -> ipfs_cid (up to 64B)

    All intent hashes are committed here so any party can
    audit a specific payment without revealing others (selective
    Merkle disclosure).  Note prefix: b"x402:axiom:intent"
    """

    def __init__(self) -> None:
        # session_id -> merkle_root
        self.session_roots = BoxMap(Bytes, Bytes, key_prefix=b"sr:")
        # sha256(tx_id) -> ipfs_cid
        self.intent_cids = BoxMap(Bytes, Bytes, key_prefix=b"ic:")

    # ------------------------------------------------------------------ #
    #  Session root registration
    # ------------------------------------------------------------------ #

    @abimethod()
    def register_session_root(
        self, session_id: Bytes, merkle_root: Bytes
    ) -> None:
        """
        Commit the Merkle root of all intents in a session on-chain.

        session_id  : 32-byte unique identifier for this payment session.
        merkle_root : 32-byte SHA-256 Merkle root of all intent hashes.
        """
        assert session_id.length == 32, "session_id must be 32 bytes"
        assert merkle_root.length == 32, "merkle_root must be 32 bytes"
        self.session_roots[session_id] = merkle_root

    @abimethod()
    def get_session_root(self, session_id: Bytes) -> Bytes:
        """Return the committed Merkle root for a session."""
        assert session_id in self.session_roots, "session not found"
        return self.session_roots[session_id]

    # ------------------------------------------------------------------ #
    #  Intent document CID registration
    # ------------------------------------------------------------------ #

    @abimethod()
    def register_intent(
        self,
        tx_id_hash: Bytes,
        ipfs_cid: Bytes,
        merkle_leaf: Bytes,
    ) -> None:
        """
        Link an on-chain transaction to its off-chain AgPP Intent Document.

        tx_id_hash  : sha256 of the Algorand transaction ID (32 bytes).
        ipfs_cid    : IPFS content identifier of the intent document (≤64 bytes).
        merkle_leaf : sha256 of the IntentDocument JSON (used for Merkle proof).
        """
        assert tx_id_hash.length == 32, "tx_id_hash must be 32 bytes"
        assert ipfs_cid.length <= 64, "ipfs_cid must be <= 64 bytes"
        # Store CID; merkle_leaf is logged in the note field for indexer queries
        self.intent_cids[tx_id_hash] = ipfs_cid

    @abimethod()
    def get_ipfs_cid(self, tx_id_hash: Bytes) -> Bytes:
        """Retrieve the IPFS CID for an intent, given the hash of its tx_id."""
        assert tx_id_hash in self.intent_cids, "intent not registered"
        return self.intent_cids[tx_id_hash]

    # ------------------------------------------------------------------ #
    #  Existence check (gas-efficient for SDK pre-flight)
    # ------------------------------------------------------------------ #

    @abimethod()
    def has_intent(self, tx_id_hash: Bytes) -> bool:
        """Returns True if the intent has been registered."""
        exists = tx_id_hash in self.intent_cids
        return exists
