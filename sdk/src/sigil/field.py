"""The BN254 (alt_bn128) scalar field that Circom and SnarkJS Groth16 work in."""

# Fr of BN254, as used by circom's default prime "bn128" and by circomlibjs.
P = int("30644e72e131a029b85045b68181585d2833e84879b9709143e1f593f0000001", 16)


def to_field(v: int) -> int:
    """Encode a signed integer as a field element (negatives wrap to P - |v|)."""
    v = int(v)
    if not -P < v < P:
        raise ValueError("integer out of field range")
    return v % P


def from_field(x: int) -> int:
    """Decode a field element produced by to_field back to a signed integer."""
    x = int(x) % P
    return x - P if x > P // 2 else x
