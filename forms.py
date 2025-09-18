# forms.py

import os
import json
import tempfile
import re
from datetime import datetime, date
from typing import Optional, Any, Union, cast, List, Dict

import streamlit as st
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.auth.credentials import Credentials as BaseCredentials

from sheet_io import append_row
from utils import risk_to_color_hex, LEVEL_OPTIONS
from map_builder import make_map  # dipakai untuk update peta lokal setelah submit
from config import SCOPES

LEVEL_STATE_KEY = "risk_level_value"
# NOTE: gunakan ID folder yang sesuai; ini nilai yang ada di skrip original Anda.
MAIN_FOLDER_ID = st.secrets["MAIN_FOLDER_ID"]  # Fixed: access from root level

# ----- OAuth (user) config -----
# Ambil dari secrets instead of file
TOKEN_FILE = st.secrets["token_user"]             # file token yang akan dibuat otomatis

SCOPES_USER = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets"
]

# ---------------- utility & helper functions (dari kode lama) ----------------

def _find_level_col(df):
    for c in df.columns:
        lc = c.lower()
        if "level" in lc and ("risiko" in lc or "resiko" in lc):
            return c
    return None

def _is_number_column(column_name: str) -> bool:
    number_keywords = [
        'no', 'nomor', 'nomer', 'number', 'num', 'urut'
    ]
    col_lower = column_name.lower()
    
    # Exclude specific columns yang tidak perlu helper
    excluded_keywords = [
        'nomer surat pemohonan pembungkusan',
        'nomer surat pfk', 
        'idpel',
        'no meter'
    ]
    
    # Jika kolom termasuk yang dikecualikan, return False
    for excluded in excluded_keywords:
        if excluded in col_lower:
            return False
    
    return any(keyword in col_lower for keyword in number_keywords)

def _get_last_number_from_column(df, column_name: str) -> str:
    if df is None or df.empty or column_name not in df.columns:
        return "Belum ada data"

    # convert to string and strip; replace literal 'nan'/'None'
    s = df[column_name].astype(str).fillna("").map(lambda x: x.strip())

    # filter out empty-like values
    bads = {"", "nan", "none"}
    s_filtered = s[~s.str.lower().isin(bads)]

    if s_filtered.empty:
        return "Belum ada data"

    # iterate dari bawah ke atas
    for val in s_filtered[::-1].tolist():
        if val is None:
            continue
        v = str(val).strip()
        if v == "" or v.lower() in bads or v == "0":
            continue
        # cari angka di string
        nums = re.findall(r'\d+', v)
        if nums:
            # kembalikan full string plus angka terakhir sebagai info
            return f"{v} (angka: {nums[-1]})"
        # jika string itu sendiri angka (mungkin '42' atau '42.0')
        cleaned = v.replace('.', '', 1)
        if cleaned.isdigit():
            return v
        # jika tidak ada angka, kembalikan nilai non-empty pertama yang ditemukan
        return v

    # fallback
    last_non_empty = s_filtered.iloc[-1]
    return str(last_non_empty)

def _is_date_column(column_name: str) -> bool:
    date_keywords = [
        'tanggal', 'tgl', 'date', 'waktu', 'time', 'bulan', 'tahun'
    ]
    col_lower = column_name.lower()
    if any(exclude_word in col_lower for exclude_word in ['petugas', 'nama', 'penemu']):
        return False
    return any(keyword in col_lower for keyword in date_keywords)

def _is_indicator_column(column_name: str) -> bool:
    col_lower = column_name.lower()
    indicator_keywords = [
        'indikator surat',
        'indikator bungkus',
        'indikator pfk',
        'perubahan konstruksi mandiri'
    ]
    return any(keyword in col_lower for keyword in indicator_keywords)

def _get_indicator_options(column_name: str) -> list:
    """
    Mendapatkan pilihan dropdown untuk kolom indikator tertentu
    """
    col_lower = column_name.lower()

    if 'indikator surat' in col_lower:
        return ["Surat Himbauan", "Selesai Surat Ke Muspika"]

    elif 'indikator bungkus' in col_lower:
        return ["Pengiriman Usulan Pembungkusan Kabel", "Realisasi pembungkusan", "Belum ada Tindak lanjut Bungkus"]

    elif 'indikator pfk' in col_lower:
        return ["Realisasi PFK", "Terima Permohonan PFK", "Kirim AMS PFK Up3", "Terbit Register PFK", "Tidak mau bayar PFK", "Belum ada Tindak Lanjut PFK"]

    elif 'perubahan konstruksi mandiri' in col_lower:
        return ["Usulan Rubah Konstruksi", "Belum Rubah Konstruksi", "Realisasi Rubah Kons"]

    return []

def _format_date_for_sheets(date_obj) -> str:
    """
    Format date object menjadi string dengan format DD/MM/YYYY untuk Google Sheets
    """
    if date_obj is None:
        return ""
    if isinstance(date_obj, date):
        return date_obj.strftime("%d/%m/%Y")
    return str(date_obj)

def _parse_date_from_string(date_str: str) -> date:
    """
    Parse string tanggal dengan berbagai format dan kembalikan sebagai date object
    """
    if not date_str or date_str.strip() == "":
        return date.today()

    date_formats = [
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%m/%d/%Y",
        "%Y/%m/%d",
    ]

    for fmt in date_formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue

    return date.today()

def _color_swatch(hex_color: str, label: str = "Color (otomatis)"):
    swatch_html = f"""
    <div style="margin:4px 0 12px 0;">
      <div style="display:flex;align-items:center;gap:10px;">
        <div style="width:24px;height:24px;border-radius:4px;
                    border:1px solid #ddd;background:{hex_color};"></div>
        <code>{hex_color}</code>
      </div>
      <small style="color:#6b7280;">{label}</small>
    </div>
    """
    st.markdown(swatch_html, unsafe_allow_html=True)

# ---------------- Drive helper OAuth ONLY ----------------

def get_user_credentials_oauth() -> Optional[Union[OAuthCredentials, BaseCredentials]]:
    creds: Optional[Union[OAuthCredentials, BaseCredentials]] = None

    # 1) Coba baca dari file token lokal (biar aman untuk development)
    if os.path.exists(TOKEN_FILE):
        try:
            creds = OAuthCredentials.from_authorized_user_file(TOKEN_FILE, SCOPES_USER)
        except Exception:
            creds = None

    # 2) Jika belum ada creds, coba baca dari st.secrets (Streamlit Secrets)
    if not creds and "token_user" in st.secrets:
        try:
            # st.secrets["token_user"] biasanya adalah mapping/dict
            info = dict(st.secrets["token_user"])
            # Beberapa value mungkin perlu conversion (scopes harus berupa list)
            # from_authorized_user_info menerima sebuah dict sesuai format token JSON
            creds = OAuthCredentials.from_authorized_user_info(info, SCOPES_USER)
        except Exception:
            creds = None

    # 3) Jika ada creds tapi expired, coba refresh (jika ada refresh_token)
    if creds and getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
        try:
            creds.refresh(Request())
        except Exception:
            creds = None

    # 4) Jika masih belum ada creds valid -> lakukan OAuth flow interaktif
    if not creds or not creds.valid:
        try:
            client_secret_info = {
                "installed": dict(st.secrets["client_secret"])
            }

            # Buat file temporary untuk client secret
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp_file:
                json.dump(client_secret_info, tmp_file)
                temp_client_file = tmp_file.name

            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    temp_client_file, SCOPES_USER
                )
                creds = flow.run_local_server(port=0)
            finally:
                try:
                    os.unlink(temp_client_file)
                except Exception:
                    pass

        except KeyError:
            st.warning("Client secret tidak ditemukan di secrets.toml")
            return None
        except Exception as e:
            st.error(f"Gagal menjalankan OAuth flow: {e}")
            return None

    # 5) Simpan token ke file lokal (so you can copy to secrets if needed)
    if creds and hasattr(creds, "to_json"):
        try:
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        except Exception as e:
            # tidak fatal — hanya beri tahu user
            st.warning(f"Gagal menyimpan token ke {TOKEN_FILE}: {e}")

    return creds

def create_folder_if_not_exists_oauth(service, parent_folder_id, folder_name):
    query = f"'{parent_folder_id}' in parents and name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder'"
    try:
        results = service.files().list(
            q=query,
            fields="files(id, name)",
            pageSize=10
        ).execute()
        folders = results.get('files', [])
        if not folders:
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_folder_id]
            }
            folder = service.files().create(body=file_metadata, fields='id').execute()
            return folder.get('id')
        else:
            return folders[0]['id']
    except HttpError as e:
        st.error(f"Gagal mengakses Drive untuk membuat folder: {e}")
        raise

def upload_to_drive_oauth_only(local_path: str, folder_id: Optional[str], file_name: str) -> Optional[str]:
    """
    Upload file menggunakan OAuth user credentials saja
    """
    try:
        creds = get_user_credentials_oauth()
        if not creds:
            st.error("Gagal mendapatkan kredensial OAuth")
            return None
            
        service = build("drive", "v3", credentials=creds)

        # Type hint meta agar Pylance tahu parents boleh list
        meta: Dict[str, Union[str, List[str]]] = {"name": file_name}

        if folder_id:
            meta["parents"] = [folder_id]

        media = MediaFileUpload(local_path, resumable=True)
        file = service.files().create(
            body=meta,
            media_body=media,
            fields="id, parents"
        ).execute()

        # Return URL format
        file_id = file.get("id")
        if file_id:
            return f"https://drive.google.com/uc?id={file_id}"
        return None
    except Exception as e:
        st.error(f"Gagal upload file menggunakan OAuth: {e}")
        return None

def save_uploaded_file(uploaded_file) -> Optional[str]:
    try:
        os.makedirs("temp_images", exist_ok=True)
        file_path = os.path.join("temp_images", uploaded_file.name)
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        return file_path
    except Exception as e:
        st.error(f"Gagal menyimpan gambar: {e}")
        return None

def _generate_file_name(uploaded_file, column_name: str, input_vals: Dict) -> str:
    """
    Generate nama file berdasarkan prioritas:
    1. Nama Pemilik/Penanggungjawab jika ada
    2. Alamat jika Nama Pemilik kosong
    3. Format: {identifier}_{column_name}_{original_filename}
    """
    # Cari nama pemilik dari berbagai kemungkinan nama kolom
    pemilik_keys = [
        "Nama Pemilik/Penanggungjawab", "Nama Pemilik", "Pemilik", 
        "Penanggungjawab", "Nama", "Owner"
    ]
    
    identifier = ""
    for key in pemilik_keys:
        if key in input_vals and input_vals[key] and str(input_vals[key]).strip():
            identifier = str(input_vals[key]).strip()
            break
    
    # Jika nama pemilik kosong, gunakan alamat
    if not identifier:
        alamat_keys = ["Alamat", "Address", "Lokasi", "Location"]
        for key in alamat_keys:
            if key in input_vals and input_vals[key] and str(input_vals[key]).strip():
                identifier = str(input_vals[key]).strip()
                break
    
    # Jika masih kosong, gunakan default
    if not identifier:
        identifier = "Unknown"
    
    # Bersihkan identifier dari karakter yang tidak aman untuk nama file
    identifier = re.sub(r'[<>:"/\\|?*]', '_', identifier)
    
    # Format nama file: {identifier}_{column_name}_{original_filename}
    original_name = uploaded_file.name
    final_name = f"{identifier}_{column_name}_{original_name}"
    
    return final_name

# ---------------- End helper functions ----------------

def render_input_form(df, gc):
    st.header("Tambah / Edit Data")
    st.write("Isi form untuk menambah baris baru ke Google Sheets")

    if df.columns.empty:
        st.warning("Sheet tampak tidak memiliki header kolom.")
        return

    level_col = _find_level_col(df)

    # Build pilihan level (gabungan default + existing)
    selected_level = ""
    if level_col:
        existing_levels = [x for x in df[level_col].dropna().unique().tolist() if str(x).strip() != ""]
        seen, merged = set(), []
        for x in LEVEL_OPTIONS + existing_levels:
            if x not in seen:
                merged.append(x)
                seen.add(x)

        selected_level = st.selectbox(
            label=level_col,
            options=[""] + merged,
            index=0,
            key=LEVEL_STATE_KEY,
        )
        auto_hex_preview = risk_to_color_hex(str(st.session_state.get(LEVEL_STATE_KEY, "")))
        _color_swatch(auto_hex_preview, label="Color (otomatis dari Level Resiko)")

    # FORM
    with st.form("input_form"):
        input_vals = {}

        # tampilkan disabled text input level agar user tahu
        if level_col:
            st.text_input(level_col, value=str(st.session_state.get(LEVEL_STATE_KEY, "")), disabled=True)

        # single coordinates input (user-facing)
        coordinates = st.text_input("Koordinat (Latitude, Longitude)", value="", help="Contoh: -7.93813533, 112.6332461")
        if coordinates:
            try:
                lat_str, lon_str = map(str.strip, coordinates.split(","))
                lat = float(lat_str)
                lon = float(lon_str)
            except Exception:
                st.error("Format koordinat salah. Pastikan formatnya adalah Latitude, Longitude (misal: -7.93813533, 112.6332461).")
                lat, lon = None, None
        else:
            lat, lon = None, None

        input_vals["Latitude"] = lat
        input_vals["Longitude"] = lon

        # Ketentuan skip: jangan render input untuk kolom 'koordinat' atau lat/lon/color
        SKIP_KEYS = ["latitude", "longitude", "color"]

        for c in df.columns:
            cl = c.lower()
            # skip kolom special
            if c == level_col or any(k in cl for k in SKIP_KEYS) or "koordinat" in cl or "coord" in cl:
                continue

            # Jika kolom adalah dokumentasi -> file uploader
            if "dokumentasi" in cl:
                uploaded_file = st.file_uploader(f"Upload {c} (jpg, png, jpeg)", type=["jpg", "png", "jpeg"], key=f"upload_{c}")
                if uploaded_file:
                    # Simpan nilai file untuk diproses nanti setelah semua input selesai
                    input_vals[f"_uploaded_file_{c}"] = uploaded_file
                    input_vals[f"_column_name_{c}"] = c
                    # Preview gambar
                    st.image(uploaded_file, caption=f"Preview {c}", use_column_width=True)
                input_vals[c] = ""  # Set empty dulu, akan diisi URL setelah upload
                continue

            # Jika kolom adalah penyulang -> dropdown
            if "penyulang" in cl:
                penyulang_options = ["Dinoyo", "Matos"]
                if not df.empty and c in df.columns:
                    existing_values = [x for x in df[c].dropna().unique().tolist() if str(x).strip() != ""]
                    for val in existing_values:
                        if val not in penyulang_options:
                            penyulang_options.append(val)

                selected_penyulang = st.selectbox(
                    label=c,
                    options=penyulang_options,
                    index=0,
                    help=f"Pilih {c}"
                )
                input_vals[c] = selected_penyulang
                continue

            # Jika kolom adalah indikator khusus -> dropdown
            if _is_indicator_column(c):
                indicator_options = _get_indicator_options(c)
                if not df.empty and c in df.columns:
                    existing_values = [x for x in df[c].dropna().unique().tolist() if str(x).strip() != ""]
                    for val in existing_values:
                        if val not in indicator_options:
                            indicator_options.append(val)

                all_options = [""] + indicator_options
                selected_indicator = st.selectbox(
                    label=c,
                    options=all_options,
                    index=0,
                    help=f"Pilih {c}"
                )
                input_vals[c] = selected_indicator
                continue

            # Jika kolom adalah tanggal -> date picker
            if _is_date_column(c):
                default_date = date.today()
                if not df.empty and c in df.columns:
                    existing_dates = df[c].dropna()
                    if not existing_dates.empty:
                        try:
                            last_date_str = str(existing_dates.iloc[-1])
                            if last_date_str and last_date_str != "":
                                default_date = _parse_date_from_string(last_date_str)
                        except Exception:
                            default_date = date.today()

                selected_date = st.date_input(
                    label=f"{c}",
                    value=default_date,
                    help=f"Pilih tanggal untuk {c}",
                    format="DD/MM/YYYY"
                )
                input_vals[c] = _format_date_for_sheets(selected_date)
                continue

            # Untuk kolom nomor -> tampilkan dengan informasi tambahan
            if _is_number_column(c):
                last_number = _get_last_number_from_column(df, c)
                input_vals[c] = st.text_input(
                    label=c,
                    value="",
                    help=f"Nomor terakhir: {last_number}"
                )
                continue

            # default: text input untuk kolom lainnya
            input_vals[c] = st.text_input(label=c, value="")

        submitted = st.form_submit_button("Tambah ke Google Sheets")

        if submitted:
            # validasi level
            if level_col and not st.session_state.get(LEVEL_STATE_KEY, ""):
                st.error(f"Silakan pilih {level_col} terlebih dahulu (di atas).")
                return

            level_value = st.session_state.get(LEVEL_STATE_KEY, "")
            auto_hex = risk_to_color_hex(level_value)

            # Process file uploads SETELAH semua input terkumpul - OAUTH ONLY
            with st.spinner("Mengupload file dokumentasi menggunakan OAuth..."):
                for col in df.columns:
                    if f"_uploaded_file_{col}" in input_vals and input_vals[f"_uploaded_file_{col}"] is not None:
                        uploaded_file = input_vals[f"_uploaded_file_{col}"]
                        
                        # Simpan file sementara
                        file_path = save_uploaded_file(uploaded_file)
                        if file_path:
                            try:
                                # Buat folder bulan menggunakan OAuth
                                creds = get_user_credentials_oauth()
                                if not creds:
                                    st.error("Gagal mendapatkan kredensial OAuth untuk upload")
                                    continue
                                    
                                service = build('drive', 'v3', credentials=creds)
                                month_folder = datetime.now().strftime('%B')
                                month_folder_id = create_folder_if_not_exists_oauth(service, MAIN_FOLDER_ID, month_folder)
                                
                                # Generate nama file dengan data input yang sudah lengkap
                                file_name = _generate_file_name(uploaded_file, col, input_vals)
                                
                                # Upload file menggunakan OAuth saja
                                file_url = upload_to_drive_oauth_only(file_path, month_folder_id, file_name)
                                if file_url:
                                    input_vals[col] = file_url
                                    st.success(f"File {col} berhasil diupload menggunakan OAuth")
                                else:
                                    st.warning(f"File {col} gagal diupload. Data akan disimpan tanpa lampiran.")
                                    input_vals[col] = ""
                            except Exception as e:
                                st.error(f"Error upload file {col}: {e}")
                                input_vals[col] = ""
                            finally:
                                # Hapus file sementara
                                try:
                                    os.remove(file_path)
                                except Exception:
                                    pass
                        else:
                            input_vals[col] = ""

            # Bersihkan kunci sementara dari input_vals
            temp_keys = [k for k in input_vals.keys() if k.startswith("_uploaded_file_") or k.startswith("_column_name_")]
            for temp_key in temp_keys:
                input_vals.pop(temp_key, None)

            # build row sesuai urutan kolom di sheet
            row = []
            for col in df.columns:
                cl = col.lower()
                if col == level_col:
                    row.append(level_value)
                elif "koordinat" in cl or cl == "coord" or cl == "coordinates":
                    if lat is not None and lon is not None:
                        row.append(f"{lat}, {lon}")
                    else:
                        row.append("")
                elif cl == "color":
                    row.append(auto_hex)
                elif cl in ["latitude", "lat", "longitude", "lon", "lng"]:
                    row.append("")
                elif "dokumentasi" in cl:
                    # gunakan nilai yang sudah diset dalam input_vals (hasil upload atau empty)
                    row.append(input_vals.get(col, ""))
                elif _is_date_column(col):
                    row.append(input_vals.get(col, ""))
                else:
                    row.append(input_vals.get(col, ""))

            # update session_state.df lokal (append satu row) supaya peta diperbarui
            try:
                import pandas as pd
                existing_df = st.session_state.get("df")
                if existing_df is None or existing_df.empty:
                    local_df = pd.DataFrame(columns=df.columns)
                else:
                    local_df = existing_df.copy()

                new_row = {}
                for col in df.columns:
                    cl = col.lower()
                    if col == level_col:
                        new_row[col] = level_value
                    elif "koordinat" in cl or cl == "coord" or cl == "coordinates":
                        new_row[col] = coordinates if coordinates else ""
                    elif cl == "color":
                        new_row[col] = auto_hex
                    elif cl in ["latitude", "lat"]:
                        new_row[col] = float(lat) if lat is not None else ""
                    elif cl in ["longitude", "lon", "lng"]:
                        new_row[col] = float(lon) if lon is not None else ""
                    elif _is_date_column(col):
                        new_row[col] = input_vals.get(col, "")
                    else:
                        new_row[col] = input_vals.get(col, "")

                local_df = pd.concat([local_df, pd.DataFrame([new_row])], ignore_index=True)
                st.session_state.df = cast(Any, local_df)

                try:
                    st.session_state.map = cast(Any, make_map(st.session_state.df, color_col="Color", show_all_columns=True, iframe_width=450, iframe_height=500))
                except Exception:
                    pass

            except Exception as e:
                st.warning(f"Baris sudah ditambahkan ke Sheets, namun terjadi error saat update tampilan lokal: {e}")

            st.success("Baris berhasil ditambahkan ke Google Sheets (peta diperbarui secara lokal).")

            # tampilkan ringkasan tanggal
            date_summary = []
            for col in df.columns:
                if _is_date_column(col) and col in input_vals and input_vals[col]:
                    date_summary.append(f"**{col}**: {input_vals[col]}")
            if date_summary:
                st.info("**Tanggal yang diinput:**\n" + "\n".join(date_summary))

            return
