"""Headroom PoC evaluation harness.

Compression (Headroom) and inference (boto3 Bedrock) are decoupled (D3): this
package owns both legs and the comparison between them. See CLAUDE.md / the
IMPLEMENTATION_LOG for the operating brief and the verified 0.26.0 API surface.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
