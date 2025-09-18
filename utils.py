# utils.py
import base64

# (Opsional) daftar dari implementasi lama—biarkan jika masih dipakai di tempat lain
color_choices = {
    "Lower": "#3d3d3d",
    "Low": "#7db86a",
    "Medium": "#f2e804",
    "High": "#ffaa00",
    "Emergency": "#b10202",
}

# Mapping Level (ID/EN, case-insensitive) → Hex
RISK_TO_HEX = {
    # English
    "lower": "#3d3d3d",
    "low": "#7db86a",
    "medium": "#f2e804",
    "high": "#ffaa00",
    "emergency": "#b10202",
}

LEVEL_OPTIONS = [
    "Lower", "Low", "Medium", "High", "Emergency",
]

def risk_to_color_hex(risk_value: str, default: str = "#3388ff") -> str:
    """Kembalikan hex color dari nilai level risiko (ID/EN, case-insensitive)."""
    if not risk_value:
        return default
    return RISK_TO_HEX.get(str(risk_value).strip().lower(), default)

def convert_image_to_base64(uploaded_file):
    """Mengonversi file upload (image) menjadi base64 string."""
    img_bytes = uploaded_file.read()
    return base64.b64encode(img_bytes).decode()