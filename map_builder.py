# map_builder.py
from typing import Optional, List, Tuple, Any, cast
import re

import pandas as pd
import folium
import streamlit as st
from branca.element import Element

from utils import risk_to_color_hex, LEVEL_OPTIONS

# Regular expression untuk menangkap angka float dalam string koordinat
FLOAT_RE = r"([+-]?[0-9]+(?:\.[0-9]+)?)"


def _find_level_col(columns: List[str]) -> Optional[str]:
    """
    Temukan nama kolom yang mengandung kata 'level' dan 'risiko'/'resiko' (case-insensitive).
    """
    for c in columns:
        lc = c.lower()
        if "level" in lc and ("risiko" in lc or "resiko" in lc):
            return c
    return None


def _find_indikator_surat_col(columns: List[str]) -> Optional[str]:
    """
    Temukan nama kolom yang mengandung kata 'indikator' dan 'surat' (case-insensitive).
    """
    for c in columns:
        lc = c.lower()
        if "indikator" in lc and "surat" in lc:
            return c
    return None


def _find_indikator_bungkus_col(columns: List[str]) -> Optional[str]:
    """
    Temukan nama kolom yang mengandung kata 'indikator' dan 'bungkus' (case-insensitive).
    """
    for c in columns:
        lc = c.lower()
        if "indikator" in lc and "bungkus" in lc:
            return c
    return None


def _get_color_from_row(row: pd.Series, df_cols: List[str]) -> Optional[str]:
    """
    Cek apakah ada kolom 'Color' atau 'Warna' di row, dan kembalikan nilainya jika ada.
    """
    color_col = None
    for c in df_cols:
        if c.lower() in ("color", "warna"):
            color_col = c
            break
    if color_col:
        val = row.get(color_col)
        if pd.notna(val) and str(val).strip() != "":
            return str(val).strip()
    return None


def _valid_hex(h: Optional[str]) -> bool:
    """Return True jika h adalah hex color seperti '#aabbcc' atau '#abc'."""
    if not h:
        return False
    if isinstance(h, str) and re.fullmatch(r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$", h.strip()):
        return True
    return False


def _parse_coord_from_field(val: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """
    Coba ekstrak dua angka float pertama dari string (seperti 'lat, lon' atau 'lat lon').
    Return (lat, lon) atau (None, None) kalau gagal.
    """
    if val is None:
        return None, None
    if not isinstance(val, str):
        try:
            s = str(val)
        except Exception:
            return None, None
    else:
        s = val

    found = re.findall(FLOAT_RE, s)
    if len(found) >= 2:
        try:
            lat = float(found[0])
            lon = float(found[1])
            return lat, lon
        except Exception:
            return None, None
    return None, None


def _is_blank(val: Any) -> bool:
    """True jika val kosong/NA/whitespace."""
    if val is None:
        return True
    try:
        if pd.isna(val):
            return True
    except Exception:
        pass
    try:
        if isinstance(val, str) and val.strip() == "":
            return True
    except Exception:
        pass
    return False


def _get_lat_lon_from_row(row: pd.Series, df_cols: List[str]) -> Tuple[Optional[float], Optional[float]]:
    """
    Ambil latitude & longitude dari row:
    - cek kolom latitude / lat / lintang dan longitude / lon / lng / bujur
    - jika kosong, coba parse dari kolom 'koordinat' / 'coord'
    - safe convert ke float
    """
    lat = None
    lon = None

    lat_keys = [c for c in df_cols if c.lower() in ("latitude", "lat", "lintang")]
    lon_keys = [c for c in df_cols if c.lower() in ("longitude", "lon", "lng", "bujur")]

    if lat_keys:
        lat = row.get(lat_keys[0])
    if lon_keys:
        lon = row.get(lon_keys[0])

    lat_blank = _is_blank(lat)
    lon_blank = _is_blank(lon)

    if lat_blank or lon_blank:
        coord_col = None
        for c in df_cols:
            if "koordinat" in c.lower() or "coord" in c.lower():
                coord_col = c
                break
        if coord_col:
            parsed_lat, parsed_lon = _parse_coord_from_field(row.get(coord_col, ""))
            if parsed_lat is not None and parsed_lon is not None:
                return parsed_lat, parsed_lon

    # convert jika mungkin
    lat_f = None
    lon_f = None
    try:
        if not _is_blank(lat) and not pd.isna(lat):
            lat_f = float(str(lat).strip())
    except Exception:
        lat_f = None

    try:
        if not _is_blank(lon) and not pd.isna(lon):
            lon_f = float(str(lon).strip())
    except Exception:
        lon_f = None

    if lat_f is not None and lon_f is not None:
        return lat_f, lon_f

    # jika hanya lat tersedia
    if lat_f is not None and lon_f is None:
        return lat_f, None

    return None, None


def _get_marker_type_from_indikator_surat(indikator_value: Optional[str]) -> str:
    """
    Tentukan jenis marker berdasarkan nilai Indikator Surat
    Returns: 'circle' atau 'square'
    """
    if not indikator_value or pd.isna(indikator_value):
        return 'circle'  # default

    value_str = str(indikator_value).strip().lower()

    if 'surat himbauan' in value_str:
        return 'square'  # persegi untuk Surat Himbauan
    elif 'selesai surat ke muspika' in value_str:
        return 'circle'  # lingkaran untuk Selesai Surat Ke Muspika
    else:
        return 'circle'  # default


def _get_border_color_from_indikator_bungkus(indikator_value: Optional[str]) -> str:
    """
    Tentukan warna border berdasarkan nilai Indikator Bungkus
    Returns: hex color untuk border
    """
    if not indikator_value or pd.isna(indikator_value):
        return '#000000'  # hitam default

    value_str = str(indikator_value).strip().lower()

    if 'pengiriman usulan' in value_str:
        return '#ff6b35'  # orange - untuk usulan/proses awal
    elif 'realisasi pembungkusan' in value_str:
        return '#28a745'  # hijau - untuk selesai/realisasi
    elif 'belum ada tindak lanjut' in value_str:
        return '#dc3545'  # merah - untuk belum ada tindakan
    else:
        return '#000000'  # hitam default


def make_map(df: pd.DataFrame,
             color_col: str = "Color",
             popup_cols: Optional[List[str]] = None,
             show_all_columns: bool = True,
             iframe_width: int = 400,
             iframe_height: int = 400,
             show_legend: bool = True) -> Optional[folium.Map]:
    """
    Bangun peta folium dari DataFrame df.
    - popup_cols: list kolom eksplisit yang ingin ditampilkan (jika None dan show_all_columns=True -> tampilkan semua)
    - show_all_columns: jika True -> tampilkan semua kolom yang tidak kosong
    - iframe_width/iframe_height: ukuran popup dalam pixel
    - show_legend: jika True -> sisipkan legend overlay ke peta (default True)
    """
    if df is None or df.empty:
        st.info("Tidak ada data untuk dipetakan.")
        return None

    df_cols = df.columns.tolist()

    # Hitung centroid dari titik valid supaya map center lebih relevan
    lats: List[float] = []
    lons: List[float] = []
    for _, row in df.iterrows():
        lat, lon = _get_lat_lon_from_row(row, df_cols)
        if lat is not None and lon is not None:
            lats.append(lat)
            lons.append(lon)

    if lats and lons:
        mean_lat = float(pd.Series(lats).mean())
        mean_lon = float(pd.Series(lons).mean())
    else:
        # fallback coordinate (0,0) jika tidak ada titik valid
        mean_lat, mean_lon = 0, 0

    m = folium.Map(location=[mean_lat, mean_lon], zoom_start=12)

    level_col = _find_level_col(df_cols)
    indikator_surat_col = _find_indikator_surat_col(df_cols)
    indikator_bungkus_col = _find_indikator_bungkus_col(df_cols)

    for _, row in df.iterrows():
        lat, lon = _get_lat_lon_from_row(row, df_cols)
        if lat is None or lon is None:
            # skip baris tanpa koordinat valid
            continue

        # Tentukan warna marker: prioritas -> kolom Color/warna -> warna arg color_col -> derive dari level -> default
        fill_color = _get_color_from_row(row, df_cols)
        if not _valid_hex(fill_color):
            if color_col in df_cols:
                fill_color = row.get(color_col)
            else:
                fill_color = None

        if not _valid_hex(fill_color) and level_col:
            fill_color = risk_to_color_hex(row.get(level_col, ""))

        if not _valid_hex(fill_color):
            fill_color = "#3388ff"

        # Tentukan bentuk marker berdasarkan Indikator Surat
        marker_type = 'circle'  # default
        if indikator_surat_col:
            indikator_surat_value = row.get(indikator_surat_col)
            marker_type = _get_marker_type_from_indikator_surat(indikator_surat_value)

        # Tentukan warna border berdasarkan Indikator Bungkus
        border_color = '#000000'  # default hitam
        if indikator_bungkus_col:
            indikator_bungkus_value = row.get(indikator_bungkus_col)
            border_color = _get_border_color_from_indikator_bungkus(indikator_bungkus_value)

        # Tentukan kolom yang akan ditampilkan pada popup
        if popup_cols and isinstance(popup_cols, (list, tuple)) and len(popup_cols) > 0:
            # Gunakan kolom yang sudah ditentukan
            cols_to_show = [c for c in popup_cols if c in df_cols]
        elif show_all_columns:
            # Tampilkan semua kolom yang ada datanya
            cols_to_show: List[str] = []
            for c in df_cols:
                val = row.get(c, "")
                # Skip kolom yang kosong atau hanya berisi whitespace
                if pd.isna(val):
                    continue
                s = str(val).strip()
                if s == "" or s == "0":
                    continue
                cols_to_show.append(c)
        else:
            # Fallback: tampilkan beberapa kolom pertama yang tidak kosong
            cols_to_show = []
            for c in df_cols:
                if len(cols_to_show) >= 6:
                    break
                val = row.get(c, "")
                if pd.isna(val):
                    continue
                s = str(val).strip()
                if s == "":
                    continue
                cols_to_show.append(c)

        # Fallback minimal bila cols_to_show kosong
        if not cols_to_show:
            fallback = [c for c in df_cols if c.lower() in ("alamat", "nama pemilik", "penemu", "koordinat")]
            cols_to_show = (fallback[:3] + df_cols[:3])[:max(1, min(len(df_cols), 3))]

        # Bangun HTML popup dengan styling yang lebih baik
        popup_html = f"""
        <div style='padding:12px;font-family:Arial, sans-serif;max-width:{iframe_width-40}px;'>
            <h4 style='margin:0 0 12px 0;color:#1f2937;border-bottom:2px solid #3b82f6;padding-bottom:6px;'>Detail Informasi</h4>
        """

        for c in cols_to_show:
            val = row.get(c, "")
            if pd.isna(val):
                val = ""
            # Safe conversion to string
            try:
                s_val = str(val)
            except Exception:
                s_val = ""

            # Skip jika kosong
            if s_val.strip() == "" or s_val.strip() == "0":
                continue

            # Styling khusus untuk URL/link
            if s_val.startswith("http"):
                s_val = f'<a href="{s_val}" target="_blank" style="color:#3b82f6;">Lihat Dokumentasi</a>'

            popup_html += f"""
            <div style='margin-bottom:8px;padding:6px;background-color:#f8fafc;border-radius:4px;'>
                <strong style='color:#374151;'>{c}:</strong>
                <span style='color:#1f2937;'>{s_val}</span>
            </div>
            """

        popup_html += "</div>"

        # Bungkus HTML ke dalam IFrame agar popup punya ukuran tetap dan scrollable
        iframe = folium.IFrame(html=popup_html,
                               width=str(iframe_width),
                               height=str(iframe_height))

        popup = folium.Popup(iframe, max_width=iframe_width)

        # Pilih jenis marker berdasarkan marker_type dengan border color
        if marker_type == 'square':
            # Gunakan RegularPolygonMarker untuk persegi
            folium.RegularPolygonMarker(
                location=(lat, lon),
                number_of_sides=4,  # 4 sisi untuk persegi
                radius=10,
                color=border_color,  # warna border dari Indikator Bungkus
                weight=3,           # ketebalan border
                fill=True,
                fill_color=fill_color,  # warna fill dari Level Risiko
                fill_opacity=0.9,
                popup=popup,
            ).add_to(m)
        else:
            # Default: CircleMarker untuk lingkaran
            folium.CircleMarker(
                location=(lat, lon),
                radius=8,
                color=border_color,     # warna border dari Indikator Bungkus
                weight=3,              # ketebalan border
                fill=True,
                fill_color=fill_color, # warna fill dari Level Risiko
                fill_opacity=0.9,
                popup=popup,
            ).add_to(m)

    # Tambah legend overlay ke peta (jika diminta)
    if show_legend:
        # bangun HTML legend berdasarkan LEVEL_OPTIONS & fungsi warna
        level_rows = ""
        for lvl in LEVEL_OPTIONS:
            hexc = risk_to_color_hex(lvl)
            level_rows += f"""
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                    <div style="width:16px;height:12px;background:{hexc};border-radius:3px;box-shadow:0 0 0 1px rgba(0,0,0,0.06);"></div>
                    <div style="font-size:13px;color:#111;">{lvl}</div>
                </div>
            """

        # contoh indikator surat shapes
        indikator_shapes_html = """
            <div style="display:flex;flex-direction:column;gap:6px;margin-top:6px;">
                <div style="display:flex;align-items:center;gap:8px;">
                    <svg width="16" height="16"><circle cx="8" cy="8" r="6" fill="#444"/></svg>
                    <div style="font-size:13px;">Selesai Surat - (lingkaran)</div>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <svg width="16" height="16" viewBox="0 0 16 16"><polygon points="3,3 13,3 13,13 3,13" fill="#444"/></svg>
                    <div style="font-size:13px;">Surat Himbauan - (persegi)</div>
                </div>
            </div>
        """

        # contoh border untuk indikator bungkus (sama dengan function mapping)
        bungkus_html = """
            <div style="display:flex;flex-direction:column;gap:6px;margin-top:6px;">
                <div style="display:flex;align-items:center;gap:8px;">
                    <div style="width:22px;height:14px;background:#fff;border:3px solid #ff6b35;"></div>
                    <div style="font-size:13px;">Pengiriman Usulan</div>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <div style="width:22px;height:14px;background:#fff;border:3px solid #28a745;"></div>
                    <div style="font-size:13px;">Realisasi Pembungkusan</div>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <div style="width:22px;height:14px;background:#fff;border:3px solid #dc3545;"></div>
                    <div style="font-size:13px;">Belum Ada Tindak Lanjut</div>
                </div>
            </div>
        """

        legend_html = f"""
        <div id="map-legend" style="
            position: absolute;
            top: 12px;
            right: 12px;
            z-index: 9999;
            background: rgba(255,255,255,0.95);
            padding: 10px;
            border-radius: 8px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.12);
            font-family: Arial, sans-serif;
            font-size: 13px;
            max-width:220px;
            pointer-events: auto;
        ">
            <div style="font-weight:700;margin-bottom:8px;color:#0f172a;">Legenda Peta</div>
            <div style="font-weight:600;margin-bottom:6px;color:#111;">Level Resiko (isi)</div>
            {level_rows}
            <div style="font-weight:600;margin-top:8px;margin-bottom:6px;color:#111;">Indikator Surat (bentuk)</div>
            {indikator_shapes_html}
            <div style="font-weight:600;margin-top:8px;margin-bottom:6px;color:#111;">Indikator Bungkus (border)</div>
            {bungkus_html}
        </div>
        """

        try:
            # m.get_root() sebenarnya mengembalikan Figure yang memiliki atribut `html`,
            # tetapi Pylance/typing stubs kadang tidak mengenal atribut ini – jadi kita cast ke Any.
            root = m.get_root()
            root_any = cast(Any, root)
            root_any.html.add_child(Element(legend_html))
        except Exception:
            # jangan crash aplikasi jika penambahan legend gagal; fallback ke sidebar legend
            try:
                st.warning("Tidak dapat menambahkan legend overlay ke peta (fallback ke sidebar legend).")
            except Exception:
                pass
    return m