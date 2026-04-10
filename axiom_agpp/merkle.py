"""
AXIOM AgPP — Merkle Tree

Builds SHA-256 Merkle trees over payment intent hashes for a session.
Allows selective disclosure: prove any single payment to a regulator
without revealing any other payment in the session.

The session Merkle root is committed on-chain via IntentRegistry.
Individual proofs are computed offline and verified against the root.

Usage:
    tree = MerkleTree([intent1.hash(), intent2.hash(), intent3.hash()])
    root = tree.get_root()
    proof = tree.get_proof(index=1)
    assert tree.verify(intent2.hash(), proof, root)
"""

import hashlib
from typing import List


def _h(data: bytes) -> bytes:
    """SHA-256 hash helper."""
    return hashlib.sha256(data).digest()


class MerkleTree:
    """
    SHA-256 Merkle tree with proof generation and verification.

    Leaves are hashed on insertion. Odd layers are padded by
    duplicating the last element (standard Merkle construction).
    """

    def __init__(self, leaves: List[bytes]):
        """
        Build a Merkle tree from a list of leaf data.

        Args:
            leaves: Raw leaf data (each will be SHA-256 hashed).
        """
        self.leaves = [_h(leaf) for leaf in leaves]
        self.tree = self._build()

    def _build(self) -> List[List[bytes]]:
        """Build the tree bottom-up, returning all layers."""
        if not self.leaves:
            return [[]]

        layer = self.leaves[:]
        tree = [layer]

        while len(layer) > 1:
            # Pad odd layers by duplicating the last node
            if len(layer) % 2 == 1:
                layer = layer + [layer[-1]]

            # Hash pairs to build the next layer
            layer = [
                _h(layer[i] + layer[i + 1])
                for i in range(0, len(layer), 2)
            ]
            tree.append(layer)

        return tree

    def get_root(self) -> bytes:
        """
        Get the Merkle root hash.

        Returns:
            32-byte SHA-256 root hash. Empty bytes if tree is empty.
        """
        if self.tree and self.tree[-1]:
            return self.tree[-1][0]
        return b""

    def get_proof(self, index: int) -> list:
        """
        Generate a Merkle proof for the leaf at the given index.

        The proof is a list of (sibling_hash, is_left) tuples where
        is_left=True means the sibling is on the LEFT side during
        hash concatenation (so: hash(sibling + node)).

        Args:
            index: Zero-based index of the leaf to prove.

        Returns:
            List of (sibling_hash, is_left) tuples from leaf to root.

        Raises:
            IndexError: If index is out of range.
        """
        if index < 0 or index >= len(self.leaves):
            raise IndexError(
                f"Leaf index {index} out of range (0-{len(self.leaves) - 1})"
            )

        proof = []
        for layer in self.tree[:-1]:
            sibling = index ^ 1  # XOR to get sibling index
            if sibling < len(layer):
                # is_left=True means sibling is at a lower index (left)
                is_left = sibling < index
                proof.append((layer[sibling], is_left))
            index //= 2

        return proof

    def verify(self, leaf: bytes, proof: list, root: bytes) -> bool:
        """
        Verify a Merkle proof for a leaf against a known root.

        This is the selective disclosure mechanism: given a leaf hash
        and its proof, anyone can verify it belongs to the committed
        root — without seeing any other leaf.

        Args:
            leaf:  Raw leaf data (will be hashed).
            proof: List of (sibling_hash, is_left) tuples from get_proof().
            root:  Expected Merkle root to verify against.

        Returns:
            True if the proof is valid (leaf is in the tree).
        """
        node = _h(leaf)
        for sibling, is_left in proof:
            if is_left:
                # Sibling is on the left → hash(sibling + node)
                node = _h(sibling + node)
            else:
                # Sibling is on the right → hash(node + sibling)
                node = _h(node + sibling)
        return node == root

    def __len__(self) -> int:
        return len(self.leaves)

    def __repr__(self) -> str:
        root_hex = self.get_root().hex()[:16] if self.get_root() else "empty"
        return f"MerkleTree(leaves={len(self.leaves)}, root={root_hex}...)"
