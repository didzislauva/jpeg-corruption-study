from __future__ import annotations

"""
ICC profile constants shared by APP2 decoding and editing code.
"""

ICC_PROFILE_SIGNATURE = b"ICC_PROFILE\x00"

# Editable APP2/ICC form fields mapped to ICC tag signatures.
ICC_TEXT_TAG_FIELDS = {
    "desc": "desc",
    "cprt": "cprt",
    "dmnd": "dmnd",
    "dmdd": "dmdd",
}

ICC_XYZ_TAG_FIELDS = {
    "wtpt": "wtpt",
    "bkpt": "bkpt",
    "rxyz": "rXYZ",
    "gxyz": "gXYZ",
    "bxyz": "bXYZ",
}

ICC_GAMMA_TAG_FIELDS = {
    "rtrc": "rTRC",
    "gtrc": "gTRC",
    "btrc": "bTRC",
}

ICC_EDITABLE_TEXT_FIELDS = ("desc", "cprt", "dmnd", "dmdd")
ICC_EDITABLE_XYZ_FIELDS = ("wtpt", "bkpt", "rxyz", "gxyz", "bxyz")
ICC_EDITABLE_GAMMA_FIELDS = ("rtrc", "gtrc", "btrc")
ICC_EDITABLE_FIELDS = ICC_EDITABLE_TEXT_FIELDS + ICC_EDITABLE_XYZ_FIELDS + ICC_EDITABLE_GAMMA_FIELDS
