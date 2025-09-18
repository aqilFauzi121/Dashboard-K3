# app.py
import pandas as pd
from pathlib import Path
import streamlit as st
from auth import get_gspread_client
from sheet_io import read_sheet_values
from map_builder import make_map
from forms import render_input_form
import hashlib

# Layout lebar
st.set_page_config(page_title="Input Data & Map", layout="wide")

# ----------------- CSS -----------------
css_path = Path(__file__).resolve().parent / "styles.css"
try:
    css = css_path.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
except FileNotFoundError:
    st.warning("styles.css tidak ditemukan - pastikan berada di folder yang sama dengan app.py.")

# --- Helper: normalisasi tipe & tampilan (tidak ubah Sheets) ---
FORCE_STRING_COLS = ["Nomer Surat Permohonan Pembungkusan"]

def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    obj_cols = df.select_dtypes(include=["object"]).columns.tolist()
    if obj_cols:
        df[obj_cols] = df[obj_cols].astype("string")
    for c in FORCE_STRING_COLS:
        if c in df.columns:
            df[c] = df[c].astype("string").str.strip()
    for c in ["Latitude", "Longitude"]:
        if c in df.columns:
            df[c] = pd.to_numeric(
                df[c].astype("string").str.replace(",", ".", regex=False),
                errors="coerce"
            )
    return df

def _pretty_df(df: pd.DataFrame) -> pd.DataFrame:
    pretty = df.copy()
    for c in FORCE_STRING_COLS:
        if c in pretty.columns:
            pretty[c] = pretty[c].replace({"0": "", 0: ""})
    return pretty

def _get_data_hash(df: pd.DataFrame) -> str:
    """Generate hash dari DataFrame untuk deteksi perubahan data"""
    if df.empty:
        return "empty"
    # Buat string representasi dari data penting
    data_str = str(df.shape) + str(df.columns.tolist())
    if not df.empty:
        data_str += str(df.iloc[0].tolist() if len(df) > 0 else "")
        data_str += str(df.iloc[-1].tolist() if len(df) > 0 else "")
    return hashlib.md5(data_str.encode()).hexdigest()

@st.cache_data(ttl=300)  # Cache selama 5 menit
def load_sheets_data():
    """Load data dari Google Sheets dengan caching"""
    try:
        gc = get_gspread_client()
        df_raw = read_sheet_values(gc)
        df_normalized = _normalize_df(df_raw)
        return df_normalized, None
    except Exception as e:
        return None, str(e)

# ----------------- MAIN APP -----------------
def main():
    st.title("Form Input & Map - terhubung Google Sheets")

    # Initialize session state untuk kontrol refresh
    if "last_data_hash" not in st.session_state:
        st.session_state.last_data_hash = ""
    if "force_refresh" not in st.session_state:
        st.session_state.force_refresh = False
    if "df" not in st.session_state:
        st.session_state.df = pd.DataFrame()

    # Load data (dengan caching)
    with st.spinner("Membaca data dari Google Sheets."):
        df_from_sheets, error = load_sheets_data()
        
        if error:
            st.error(f"Gagal membaca Google Sheets: {error}")
            return
        
        if df_from_sheets is None:
            st.error("Data tidak dapat dimuat dari Google Sheets")
            return

    # Cek apakah data berubah
    current_hash = _get_data_hash(df_from_sheets)
    data_changed = current_hash != st.session_state.last_data_hash

    # Update session state jika data berubah atau force refresh
    if data_changed or st.session_state.force_refresh or st.session_state.df.empty:
        st.session_state.df = df_from_sheets
        st.session_state.last_data_hash = current_hash
        st.session_state.force_refresh = False

    # Tombol refresh manual
    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        if st.button("Refresh Data dari Sheets"):
            # Clear cache dan force refresh
            load_sheets_data.clear()
            st.session_state.force_refresh = True
            st.rerun()
    
    with col_info:
        if data_changed:
            st.success("Data ter-update otomatis dari Sheets")
        
        # Tambahkan debug button
        if st.button("Debug: Show Raw Data"):
            st.write("**Data dari Session State:**")
            st.write(f"Jumlah baris: {len(st.session_state.df)}")
            st.dataframe(st.session_state.df)
            
            # Baca data fresh langsung dari Sheets
            st.write("**Data Fresh dari Google Sheets:**")
            try:
                fresh_df, error = load_sheets_data()
                if fresh_df is not None:
                    st.write(f"Jumlah baris: {len(fresh_df)}")
                    st.dataframe(fresh_df)
                    
                    # Cek data yang berbeda
                    if not fresh_df.equals(st.session_state.df):
                        st.warning("Data session state berbeda dengan data di Sheets!")
                else:
                    st.error(f"Error loading fresh data: {error}")
            except Exception as e:
                st.error(f"Error: {e}")
    
    with col_info:
        if data_changed:
            st.success("Data ter-update otomatis dari Sheets")

    df_session = st.session_state.df

    # Get gspread client untuk form (tanpa cache karena diperlukan untuk write)
    try:
        gc = get_gspread_client()
    except Exception as e:
        st.error(f"Gagal membuat gspread client untuk form: {e}")
        return

    # layout dua kolom utama: kiri = form + kontrol, kanan = peta
    col1, col2 = st.columns([1, 2], gap="large")

    # ---------- KIRI: Form + preview ----------
    with col1:
        try:
            render_input_form(df_session, gc)
        except Exception as e:
            st.error(f"Terjadi error di form input: {e}")

        st.markdown("---")
        st.write("Preview data (session):")
        st.dataframe(_pretty_df(df_session), width='stretch')

    # ---------- KANAN: Bangun & tampilkan peta ----------
    # Cache map jika data tidak berubah
    if "map_hash" not in st.session_state:
        st.session_state.map_hash = ""
    if "cached_map" not in st.session_state:
        st.session_state.cached_map = None

    current_map_hash = _get_data_hash(df_session)
    
    # Rebuild map hanya jika data berubah
    if current_map_hash != st.session_state.map_hash or st.session_state.cached_map is None:
        try:
            st.session_state.cached_map = make_map(
                df_session, 
                color_col="Color", 
                show_all_columns=True, 
                iframe_width=450, 
                iframe_height=500
            )
            st.session_state.map_hash = current_map_hash
        except Exception as e:
            st.warning(f"Gagal membangun peta: {e}")
            st.session_state.cached_map = None

    with col2:
        st.header("Peta Lokasi")
        # Fallback legend di sidebar/kolom peta (selalu ditampilkan)
        with st.expander("Legenda Peta (klik untuk lihat)"):
            st.markdown("""
            <div style="font-family:Arial,sans-serif;">
            <b>Level Resiko (warna isi)</b><br>
            <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
              <div style="width:16px;height:12px;background:#3d3d3d;border-radius:3px"></div> Lower
            </div>
            <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
              <div style="width:16px;height:12px;background:#7db86a;border-radius:3px"></div> Low
            </div>
            <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
              <div style="width:16px;height:12px;background:#f2e804;border-radius:3px"></div> Medium
            </div>
            <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
              <div style="width:16px;height:12px;background:#ffaa00;border-radius:3px"></div> High
            </div>
            <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
              <div style="width:16px;height:12px;background:#b10202;border-radius:3px"></div> Emergency
            </div>

            <hr />

            <b>Indikator Surat (bentuk)</b><br>
            <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
              <svg width="16" height="16"><circle cx="8" cy="8" r="6" fill="#444"/></svg> Selesai Surat (lingkaran)
            </div>
            <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
              <svg width="16" height="16" viewBox="0 0 16 16"><polygon points="3,3 13,3 13,13 3,13" fill="#444"/></svg> Surat Himbauan (persegi)
            </div>

            <hr />
            <b>Indikator Bungkus (warna border)</b><br>
            <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
              <div style="width:22px;height:14px;background:#fff;border:3px solid #ff6b35"></div> Pengiriman Usulan
            </div>
            <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
              <div style="width:22px;height:14px;background:#fff;border:3px solid #28a745"></div> Realisasi Pembungkusan
            </div>
            <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
              <div style="width:22px;height:14px;background:#fff;border:3px solid #dc3545"></div> Belum Ada Tindak Lanjut
            </div>
            </div>
            """, unsafe_allow_html=True)

        cached_map = st.session_state.cached_map

        if cached_map is not None:
            try:
                from streamlit_folium import st_folium
                # Gunakan key yang stabil untuk menghindari re-render tidak perlu
                map_data = st_folium(
                    cached_map, 
                    width=1200, 
                    height=800,
                    key="main_map"  # Key stabil untuk menghindari re-render
                )
            except Exception as e:
                st.error(f"Gagal menampilkan peta: {e}")
        else:
            st.info("Peta belum tersedia (pastikan kolom koordinat ada dan data valid).")

if __name__ == "__main__":
    main()